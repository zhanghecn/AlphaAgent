"""AkShare source-tree adapter used by AlphaAgent.

AkShare keeps a very broad public API in ``akshare.__init__``. AlphaAgent loads
only the concrete source files it needs so API startup does not depend on every
AkShare optional interface.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import json
import logging
import math
import os
import random
import re
import sys
import threading
import time
import types
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from alphaagent.market.cache import TTLCache, market_cache
from alphaagent.market.boards import stock_board_payload
from alphaagent.market.models import DataSourceStatus, Quote
from alphaagent.market.symbols import INDEX_SYMBOLS, eastmoney_secid, normalize_exchange, vt_symbol


logger = logging.getLogger(__name__)

QUOTE_TTL_SECONDS = 10
LIST_TTL_SECONDS = 10
FULL_LIST_TTL_SECONDS = 60
FULL_MARKET_TTL_SECONDS = 20
FULL_MARKET_PAGE_SIZE = 200
FULL_MARKET_MAX_WORKERS = 6
FULL_MARKET_OHLCV_SPOT_PAGE_SIZE = 100
FULL_MARKET_OHLCV_SPOT_MAX_WORKERS = 6
FULL_MARKET_OHLCV_SPOT_MIN_COVERAGE_RATIO = 0.99
FULL_MARKET_OHLCV_SPOT_REQUEST_TIMEOUT_SECONDS = 20
FULL_MARKET_OHLCV_SPOT_FETCH_TIMEOUT_SECONDS = 90
EASTMONEY_LIVE_PAGE_MAX_AGE_SECONDS = 20
EASTMONEY_LIVE_PAGE_MIN_FRESH_RATIO = 0.90
OVERVIEW_TTL_SECONDS = 30
BARS_TTL_SECONDS = 600
BUSINESS_TTL_SECONDS = 86400
FINANCIAL_PERFORMANCE_TTL_SECONDS = 6 * 60 * 60
FINANCIAL_PERFORMANCE_PAGE_SIZE = 500
FINANCIAL_PERFORMANCE_MAX_PAGES = 100
FINANCIAL_PERFORMANCE_REQUEST_TIMEOUT_SECONDS = 20
SECTOR_TTL_SECONDS = 86400
SOURCE_STATUS_TTL_SECONDS = 300
SW_TREE_TTL_SECONDS = 86400 * 7
SW_CONSTITUENTS_TTL_SECONDS = 86400
SW_CLASSIFY_TTL_SECONDS = 86400 * 3
SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS = 800
SECTOR_DAILY_MAX_HISTORY_SESSIONS = 1_000
SHANGHAI = ZoneInfo("Asia/Shanghai")
_EASTMONEY_SESSION_LOCAL = threading.local()


def _copy_full_market_quote_payload(value: object) -> object:
    """Isolate mutable containers while sharing only scalar quote values."""

    if not isinstance(value, Mapping):
        return value
    copied = dict(value)
    items = value.get("items")
    if isinstance(items, list):
        copied["items"] = [
            dict(item) if isinstance(item, Mapping) else item
            for item in items
        ]
    return copied


_FULL_MARKET_QUOTE_CACHE = TTLCache(
    max_items=FULL_MARKET_MAX_WORKERS,
    copier=_copy_full_market_quote_payload,
)
_FULL_MARKET_OHLCV_SPOT_CACHE = TTLCache(
    max_items=FULL_MARKET_OHLCV_SPOT_MAX_WORKERS,
    copier=_copy_full_market_quote_payload,
)


class AkShareSourceError(RuntimeError):
    """Raised when the vendored AkShare source tree cannot serve a request."""


@dataclass(frozen=True)
class AkShareSourceInfo:
    """Runtime information for the integrated AkShare source tree."""

    root: Path
    package_dir: Path
    version: str

    def to_api(self) -> dict[str, Any]:
        return {
            "name": "akshare",
            "version": self.version,
            "source_root": str(self.root),
            "package_dir": str(self.package_dir),
        }


class AkShareAdapter:
    """Small AlphaAgent-facing facade over the integrated AkShare source."""

    def __init__(self, source_root: Path | None = None) -> None:
        self.source_root = source_root or _default_source_root()
        self.package_dir = self.source_root / "akshare"
        if not self.package_dir.exists():
            raise AkShareSourceError(f"AkShare source package not found: {self.package_dir}")
        source_path = str(self.source_root)
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
        self._install_namespace_package()

    def info(self) -> AkShareSourceInfo:
        """Return source-tree metadata without importing the full package API."""

        version = "unknown"
        version_file = self.package_dir / "_version.py"
        namespace: dict[str, Any] = {}
        if version_file.exists():
            exec(version_file.read_text(encoding="utf-8"), namespace)
            version = str(namespace.get("__version__") or version)
        return AkShareSourceInfo(root=self.source_root, package_dir=self.package_dir, version=version)

    def _install_namespace_package(self) -> None:
        """Expose AkShare source subpackages without executing its broad API init."""

        _install_package_stub("akshare", self.package_dir)
        for name in ("index", "stock", "stock_feature", "stock_fundamental", "stock_industry", "news", "utils"):
            _install_package_stub(f"akshare.{name}", self.package_dir / name)

    def probe(self) -> dict[str, Any]:
        """Run bounded real AkShare calls for Docker/API smoke testing."""

        started = datetime.now(timezone.utc)
        checks = [
            ("source_tree", self.info),
            ("a_share_spot", lambda: self.list_stocks(page=1, page_size=3)),
            ("indices", lambda: {"items": [quote.to_api() for quote in self.get_indices()]}),
            ("concept_boards", lambda: self.board_names("concept", limit=3)),
            ("industry_boards", lambda: self.board_names("industry", limit=3)),
            ("sample_stock_kline", lambda: self._probe_stock_bars(limit=5)),
            ("sample_business_segments", lambda: self._probe_business_segments(limit=3)),
            ("sample_sector_members", lambda: self._probe_sector_members(limit=3)),
        ]
        results: list[dict[str, Any]] = []
        for name, fn in checks:
            try:
                payload = fn()
                count = _payload_count(payload)
                sample = _payload_sample(payload)
                results.append({"name": name, "ok": True, "count": count, "sample": sample})
            except Exception as exc:
                results.append({"name": name, "ok": False, "error": exc.__class__.__name__, "message": str(exc)[:300]})

        return {
            **self.info().to_api(),
            "ok": any(item["ok"] for item in results if item["name"] != "source_tree"),
            "checks": results,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }

    def _probe_stock_bars(self, limit: int = 5) -> dict[str, Any]:
        last_error: Exception | None = None
        for stock in self._sample_stocks(limit=8):
            try:
                payload = self.stock_bars(str(stock["symbol"]), str(stock.get("exchange") or ""), limit=limit, interval="1d")
                if payload.get("items"):
                    return payload
            except Exception as exc:
                last_error = exc
                continue
        raise AkShareSourceError(f"No sampled stock returned kline data: {last_error.__class__.__name__ if last_error else 'empty'}")

    def _probe_business_segments(self, limit: int = 3) -> dict[str, Any]:
        last_payload: dict[str, Any] | None = None
        last_error: Exception | None = None
        for stock in self._sample_stocks(limit=8):
            try:
                payload = self.stock_business_segments(str(stock["symbol"]), str(stock.get("exchange") or ""), limit=limit)
                if payload.get("items"):
                    return payload
                last_payload = payload
            except Exception as exc:
                last_error = exc
                continue
        if last_payload is not None:
            return last_payload
        raise AkShareSourceError(f"No sampled stock returned business segments: {last_error.__class__.__name__ if last_error else 'empty'}")

    def _probe_sector_members(self, limit: int = 3) -> dict[str, Any]:
        last_error: Exception | None = None
        for sector in self._sample_boards(limit=8):
            try:
                payload = self.board_members(str(sector["type"]), str(sector["id"]), limit=limit)
                if payload.get("items"):
                    return payload
            except Exception as exc:
                last_error = exc
                continue
        raise AkShareSourceError(f"No sampled board returned constituents: {last_error.__class__.__name__ if last_error else 'empty'}")

    def _sample_stocks(self, limit: int = 8) -> list[dict[str, Any]]:
        data = self.list_stocks(page=1, page_size=limit, sort="amount")
        stocks = [
            item
            for item in _payload_items(data)
            if item.get("symbol")
        ]
        if not stocks:
            raise AkShareSourceError("No sample stocks returned by live stock list")
        return stocks

    def _sample_boards(self, limit: int = 8) -> list[dict[str, Any]]:
        boards: list[dict[str, Any]] = []
        for board_type in ("concept", "industry"):
            data = self.board_names(board_type, limit=limit)
            boards.extend(
                item
                for item in _payload_items(data)
                if item.get("id") and item.get("type")
            )
        if not boards:
            raise AkShareSourceError("No sample boards returned by live board list")
        return boards

    def a_share_spot(self, limit: int = 20) -> dict[str, Any]:
        """Return real A-share spot rows through AkShare.

        The Tencent AkShare adapter is used for interactive smoke tests because
        it returns a bounded page. EastMoney's full A-share adapter remains
        available in the source tree for later background synchronization.
        """

        return market_cache.get_or_set(f"a_share_spot:{limit}", LIST_TTL_SECONDS, lambda: self._a_share_spot_uncached(limit))

    def _a_share_spot_uncached(self, limit: int) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock.stock_zh_a_tx")
        with _akshare_network_env():
            df = module.stock_zh_a_spot_tx()
        items = [_stock_row_to_api(row) for row in _records(df, limit)]
        return {
            "items": items,
            "total": len(df),
            "source": "akshare.stock_zh_a_spot_tx",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def list_stocks(self, page: int = 1, page_size: int = 50, sort: str = "mktcap", order: str = "desc") -> dict[str, Any]:
        """Return a page of live A-share quotes through fast public quote APIs."""

        key = f"list_stocks:{page}:{page_size}:{sort.strip().lower()}:{order.strip().lower()}"
        return market_cache.get_or_set(key, LIST_TTL_SECONDS, lambda: self._list_stocks_uncached(page, page_size, sort, order))

    def _list_stocks_uncached(self, page: int, page_size: int, sort: str, order: str = "desc") -> dict[str, Any]:
        offset = (max(page, 1) - 1) * min(max(page_size, 1), 200)
        count = min(max(page_size, 1), 200)
        normalized_sort = sort.strip().lower()

        # Sina 不提供期间涨幅数据，排序相关字段时跳过以避免全 null 结果
        skip_sina = normalized_sort in ("return_5d", "return_10d", "return_20d")

        if not skip_sina:
            try:
                return _sina_all_a_page(page=max(page, 1), page_size=count, sort=sort)
            except Exception:
                pass

        try:
            return _eastmoney_all_a_page(page=max(page, 1), page_size=count, sort=sort, order=order)
        except Exception:
            pass

        module = importlib.import_module("akshare.stock.stock_zh_a_tx")
        with _akshare_network_env():
            df, total = _stock_zh_a_spot_tx_page(module, offset=offset, count=count, sort=sort)
        return {
            "items": [_stock_row_to_api(row) for row in _records(df, count)],
            "page": page,
            "page_size": page_size,
            "total": total,
            "source": "akshare.stock_zh_a_spot_tx",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def research_quote_flow_page(
        self,
        page: int,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """Return fresh EastMoney fields for the isolated pre-board study."""

        normalized_page = max(int(page), 1)
        normalized_size = min(max(int(page_size), 1), 200)
        key = f"research_quote_flow:{normalized_page}:{normalized_size}"
        return market_cache.get_or_set(
            key,
            LIST_TTL_SECONDS,
            lambda: self._research_quote_flow_page_uncached(
                normalized_page,
                normalized_size,
            ),
        )

    def _research_quote_flow_page_uncached(
        self,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        payload = _eastmoney_all_a_page(
            page=page,
            page_size=page_size,
            sort="change_pct",
            order="desc",
        )
        if not _eastmoney_stock_page_is_fresh(payload):
            raise AkShareSourceError("EastMoney research quote page is stale")
        return payload

    def all_stock_quotes(
        self,
        max_workers: int = FULL_MARKET_MAX_WORKERS,
    ) -> dict[str, Any]:
        """Return one complete A-share quote snapshot using bounded pagination."""

        workers = min(max(int(max_workers), 1), FULL_MARKET_MAX_WORKERS)
        return _FULL_MARKET_QUOTE_CACHE.get_or_set(
            f"all_stock_quotes:{workers}",
            FULL_MARKET_TTL_SECONDS,
            lambda: self._all_stock_quotes_uncached(max_workers=workers),
        )

    def _all_stock_quotes_uncached(self, *, max_workers: int) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock.stock_zh_a_tx")
        with _akshare_network_env():
            first_page, total = _stock_zh_a_spot_tx_page(
                module,
                offset=0,
                count=FULL_MARKET_PAGE_SIZE,
                sort="price",
            )
            expected_rows = max(int(total or len(first_page)), len(first_page))
            offsets = range(FULL_MARKET_PAGE_SIZE, expected_rows, FULL_MARKET_PAGE_SIZE)
            frames = [first_page]
            with ThreadPoolExecutor(
                max_workers=min(max(int(max_workers), 1), FULL_MARKET_MAX_WORKERS),
                thread_name_prefix="all-stock-quotes",
            ) as executor:
                futures = [
                    executor.submit(
                        _stock_zh_a_spot_tx_page,
                        module,
                        offset,
                        FULL_MARKET_PAGE_SIZE,
                        "price",
                    )
                    for offset in offsets
                ]
                for future in as_completed(futures):
                    frame, _ = future.result()
                    frames.append(frame)

        rows: dict[str, dict[str, Any]] = {}
        for frame in frames:
            for raw_row in frame.to_dict(orient="records"):
                item = _compact_stock_row_to_api(raw_row)
                symbol = str(item.get("vt_symbol") or "")
                if symbol:
                    rows[symbol] = item

        captured_at = datetime.now(timezone.utc)
        return {
            "trade_date": captured_at.astimezone(SHANGHAI).date().isoformat(),
            "updated_at": captured_at.isoformat(),
            "items": list(rows.values()),
            "total": len(rows),
            "source": "tencent.full_a_share_pages",
        }

    def all_stock_ohlcv_spot(
        self,
        max_workers: int = FULL_MARKET_OHLCV_SPOT_MAX_WORKERS,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return a complete Sina A-share spot snapshot with intraday OHLCV."""

        workers = min(
            max(int(max_workers), 1),
            FULL_MARKET_OHLCV_SPOT_MAX_WORKERS,
        )
        cache_key = f"all_stock_ohlcv_spot:{workers}"
        loader = lambda: self._all_stock_ohlcv_spot_uncached(max_workers=workers)
        if force_refresh:
            return _FULL_MARKET_OHLCV_SPOT_CACHE.refresh(
                cache_key,
                FULL_MARKET_TTL_SECONDS,
                loader,
            )
        return _FULL_MARKET_OHLCV_SPOT_CACHE.get_or_set(
            cache_key,
            FULL_MARKET_TTL_SECONDS,
            loader,
        )

    def _all_stock_ohlcv_spot_uncached(
        self,
        *,
        max_workers: int,
    ) -> dict[str, Any]:
        """Load every Sina A-share page before exposing a usable spot snapshot."""

        with _akshare_network_env():
            try:
                source_total = _sina_sector_member_count("hs_a")
            except Exception as exc:
                raise AkShareSourceError(
                    f"Sina A-share stock count unavailable: {exc.__class__.__name__}"
                ) from exc
            if source_total is None or source_total <= 0:
                raise AkShareSourceError("Sina A-share stock count unavailable")

            page_count = math.ceil(source_total / FULL_MARKET_OHLCV_SPOT_PAGE_SIZE)
            pages: dict[int, list[dict[str, Any]]] = {}
            executor = ThreadPoolExecutor(
                max_workers=min(
                    max(int(max_workers), 1),
                    FULL_MARKET_OHLCV_SPOT_MAX_WORKERS,
                ),
                thread_name_prefix="all-stock-ohlcv-spot",
            )
            try:
                futures = {
                    executor.submit(
                        _sina_full_market_ohlcv_page,
                        page,
                    ): page
                    for page in range(1, page_count + 1)
                }
                try:
                    for future in as_completed(
                        futures,
                        timeout=FULL_MARKET_OHLCV_SPOT_FETCH_TIMEOUT_SECONDS,
                    ):
                        pages[futures[future]] = future.result()
                except TimeoutError as exc:
                    completed_pages = len(pages)
                    raise AkShareSourceError(
                        "Sina A-share spot snapshot timed out: "
                        f"{completed_pages}/{page_count} pages"
                    ) from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        items_by_symbol: dict[str, dict[str, Any]] = {}
        for page in range(1, page_count + 1):
            for raw_row in pages[page]:
                item = _sina_ohlcv_spot_row_to_api(raw_row)
                current_symbol = str(item.get("vt_symbol") or "")
                if current_symbol:
                    items_by_symbol[current_symbol] = item

        minimum_rows = math.ceil(
            source_total * FULL_MARKET_OHLCV_SPOT_MIN_COVERAGE_RATIO
        )
        if len(items_by_symbol) < minimum_rows:
            raise AkShareSourceError(
                "Sina A-share spot snapshot incomplete: "
                f"{len(items_by_symbol)}/{source_total}"
            )

        captured_at = datetime.now(timezone.utc)
        return {
            "trade_date": captured_at.astimezone(SHANGHAI).date().isoformat(),
            "updated_at": captured_at.isoformat(),
            "items": list(items_by_symbol.values()),
            "total": len(items_by_symbol),
            "source_total": source_total,
            "source": "sina.market_center.hs_a_ohlcv",
        }

    def search_stocks(self, query: str, page_size: int = 50) -> dict[str, Any]:
        """Search the current AkShare A-share universe by code, name, or vt_symbol."""

        key = f"search_stocks:{query.strip().lower()}:{page_size}"
        return market_cache.get_or_set(key, LIST_TTL_SECONDS, lambda: self._search_stocks_uncached(query, page_size))

    def _search_stocks_uncached(self, query: str, page_size: int) -> dict[str, Any]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            return self.list_stocks(page=1, page_size=page_size)

        page_size = min(max(page_size, 1), 100)
        try:
            matches = _eastmoney_search_stock_quotes(query, page_size)
            if matches:
                return {
                    "items": matches,
                    "page": 1,
                    "page_size": page_size,
                    "total": len(matches),
                    "source": "eastmoney.searchapi,eastmoney.push2",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
        except Exception:
            pass

        rows = self._all_stock_spot_rows()
        matches: list[dict[str, Any]] = []
        for row in rows:
            item = _stock_row_to_api(row)
            symbol = str(item.get("symbol") or "").lower()
            name = str(item.get("name") or "").lower()
            vt = str(item.get("vt_symbol") or "").lower()
            if normalized_query in symbol or normalized_query in name or normalized_query in vt:
                matches.append(item)
                if len(matches) >= page_size:
                    break

        return {
            "items": matches,
            "page": 1,
            "page_size": page_size,
            "total": len(matches),
            "universe_total": len(rows),
            "source": "akshare.stock_zh_a_spot_tx",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def watchlist(self, page_size: int = 50) -> dict[str, Any]:
        """Return the first live AkShare A-share page."""

        return self.list_stocks(page=1, page_size=page_size)

    def stock_detail(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Return one stock quote/detail through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        key = f"stock_detail:{symbol}:{normalized}"
        return market_cache.get_or_set(key, QUOTE_TTL_SECONDS, lambda: self._stock_detail_uncached(symbol, normalized))

    def _stock_detail_uncached(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        normalized = normalize_exchange(symbol, exchange)
        try:
            return self._stock_detail_tx(symbol, normalized)
        except Exception:
            pass

        search = self.search_stocks(symbol, page_size=20)
        symbol_matches = [item for item in search.get("items") or [] if item.get("symbol") == symbol]
        for item in search.get("items") or []:
            if item.get("symbol") == symbol and normalize_exchange(symbol, item.get("exchange")) == normalized:
                vts = vt_symbol(symbol, normalized)
                return {**item, "exchange": normalized, "vt_symbol": vts, **stock_board_payload(vts, normalized)}
        if len(symbol_matches) == 1:
            item = symbol_matches[0]
            resolved_exchange = str(item.get("exchange") or normalize_exchange(symbol))
            vts = vt_symbol(symbol, resolved_exchange)
            return {**item, "exchange": resolved_exchange, "vt_symbol": vts, **stock_board_payload(vts, resolved_exchange)}
        try:
            info = self._stock_individual_info(symbol)
        except Exception:
            info = {}
        vts = vt_symbol(symbol, normalized)
        quote = {
            "symbol": symbol,
            "exchange": normalized,
            "vt_symbol": vts,
            **stock_board_payload(vts, normalized),
            "name": info.get("股票简称") or symbol,
            "last_price": _number(info.get("最新")),
            "change": None,
            "change_pct": None,
            "open_price": None,
            "high_price": None,
            "low_price": None,
            "previous_close": None,
            "volume": None,
            "turnover": None,
            "market_cap": _number(info.get("总市值")),
            "float_market_cap": _number(info.get("流通市值")),
            "pe": None,
            "pb": None,
            "turnover_rate": None,
            "volume_ratio": None,
            "industry": info.get("行业"),
            "area": None,
            "trade_time": None,
            "source": "akshare.stock_individual_info_em",
        }
        return quote

    def _stock_detail_tx(self, symbol: str, exchange: str) -> dict[str, Any]:
        prefixed = _prefixed_symbol(symbol, exchange)
        response = requests.get(f"https://qt.gtimg.cn/q={prefixed}", timeout=8)
        response.raise_for_status()
        match = re.search(r'="(.*)"', response.text.strip())
        if not match:
            raise AkShareSourceError(f"Tencent quote returned no payload for {prefixed}")
        parts = match.group(1).split("~")
        if len(parts) < 46 or not parts[1] or not parts[2]:
            raise AkShareSourceError(f"Tencent quote payload incomplete for {prefixed}")
        quote_symbol = parts[2]
        quote_exchange = _exchange_from_prefixed_symbol(prefixed, quote_symbol)
        vts = vt_symbol(quote_symbol, quote_exchange)
        turnover = _number(parts[57] if len(parts) > 57 else None)
        return {
            "symbol": quote_symbol,
            "exchange": quote_exchange,
            "vt_symbol": vts,
            **stock_board_payload(vts, quote_exchange),
            "name": parts[1],
            "last_price": _number(parts[3]),
            "change": _number(parts[31]),
            "change_pct": _number(parts[32]),
            "open_price": _number(parts[5]),
            "high_price": _number(parts[33]),
            "low_price": _number(parts[34]),
            "previous_close": _number(parts[4]),
            "volume": _number(parts[36]),
            "turnover": round(turnover * 10_000, 2) if turnover is not None else None,
            "market_cap": _tencent_yi_yuan_to_yuan(parts[45] if len(parts) > 45 else None),
            "float_market_cap": _tencent_yi_yuan_to_yuan(parts[44] if len(parts) > 44 else None),
            "pe": _number(parts[39] if len(parts) > 39 else None),
            "pb": _number(parts[46] if len(parts) > 46 else None),
            "turnover_rate": _number(parts[38] if len(parts) > 38 else None),
            "volume_ratio": _number(parts[49] if len(parts) > 49 else None),
            "trade_time": _format_tencent_trade_time(parts[30]),
            "raw_symbol": prefixed,
            "raw": {"parts": parts},
            "source": "tencent.qt.gtimg",
        }

    def get_quotes(self, symbols: list[dict[str, str]] | tuple[dict[str, str], ...]) -> list[Quote]:
        """Return quote dataclasses for compatibility with existing API code."""

        quotes: list[Quote] = []
        for item in symbols:
            data = self.stock_detail(item["symbol"], item.get("exchange"))
            quotes.append(_quote_from_api(data))
        return quotes

    def get_indices(self) -> list[Quote]:
        """Fetch major A-share index quotes through AkShare."""

        data = market_cache.get_or_set("indices", QUOTE_TTL_SECONDS, self._get_indices_uncached)
        return [_quote_from_api(item) for item in data]

    def _get_indices_uncached(self) -> list[dict[str, Any]]:
        quotes = _eastmoney_index_quotes()
        if not quotes:
            quotes = _sina_index_quotes()
        if not quotes:
            raise AkShareSourceError("No AkShare index quotes available")
        return [quote.to_api() for quote in quotes]

    def index_detail(self, symbol: str, exchange: str | None = None, name: str | None = None) -> dict[str, Any]:
        """Return current index detail from AkShare index spot quotes."""

        normalized = normalize_exchange(symbol, exchange)
        for quote in self.get_indices():
            if quote.symbol == symbol and normalize_exchange(symbol, quote.exchange) == normalized:
                data = quote.to_api()
                if name:
                    data["name"] = name
                return data
        raise AkShareSourceError(f"No AkShare index quote available for {symbol}.{normalized}")

    def market_overview(self) -> dict[str, Any]:
        """Return market overview using AkShare index and stock adapters."""

        return market_cache.get_or_set("market_overview", OVERVIEW_TTL_SECONDS, self._market_overview_uncached)

    def _market_overview_uncached(self) -> dict[str, Any]:
        index_quotes = self.get_indices()
        stock_page = self.list_stocks(page=1, page_size=10, sort="amount")
        indices = [quote.to_api() for quote in index_quotes]
        return {
            "trade_date": self._trade_date_from_quotes(index_quotes).isoformat(),
            "indices": indices,
            "active_stocks": stock_page["items"],
            "market_state": _infer_market_state(indices),
            "source": f"{stock_page.get('source')},eastmoney.push2.index",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_bars(
        self,
        symbol: str,
        exchange: str | None = None,
        limit: int = 90,
        interval: str = "1d",
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> dict[str, Any]:
        """Return stock or index K-lines through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        normalized_interval = _normalize_interval(interval)
        start_key = _date_key(start_date) if start_date else ""
        end_key = _date_key(end_date) if end_date else ""
        key = f"stock_bars:{symbol}:{normalized}:{normalized_interval}:{limit}:{start_key}:{end_key}"
        return market_cache.get_or_set(
            key,
            BARS_TTL_SECONDS,
            lambda: self._stock_bars_uncached(symbol, normalized, limit, normalized_interval, start_key, end_key),
        )

    def _stock_bars_uncached(
        self,
        symbol: str,
        exchange: str,
        limit: int,
        interval: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_exchange(symbol, exchange)
        if _is_index_symbol(symbol, normalized):
            df, source = self._index_bars(symbol, normalized, interval, limit)
        else:
            df, source = self._stock_bars(symbol, interval, limit, start_date, end_date)
        df = _filter_bars_by_date(df, start_date, end_date)
        items = [_bar_row_to_api(row) for row in _tail_records(df, limit)]
        if not items:
            raise AkShareSourceError(f"No AkShare bar data for {symbol}")
        return {
            "symbol": symbol,
            "exchange": normalized,
            "vt_symbol": vt_symbol(symbol, normalized),
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "items": items,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_business(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Return business composition through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        key = f"stock_business:{symbol}:{normalized}"
        return market_cache.get_or_set(key, BUSINESS_TTL_SECONDS, lambda: self._stock_business_uncached(symbol, normalized))

    def _stock_business_uncached(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        segments_data = self.stock_business_segments(symbol, exchange, limit=200)
        segments = [_business_segment_to_api(item) for item in segments_data.get("items") or []]
        latest_report_date = _latest_value([item.get("report_date") for item in segments])
        latest_segments = [item for item in segments if not latest_report_date or item.get("report_date") == latest_report_date]
        main_products = [str(item["name"]) for item in latest_segments if item.get("name")][:8]
        intro: dict[str, Any] = {}
        try:
            intro = self._stock_business_intro(symbol)
        except Exception:
            intro = {}
        intro_products = _split_terms(intro.get("产品名称") or intro.get("产品类型"))
        if intro_products:
            main_products = _dedupe_strings([*intro_products, *main_products])[:12]
        return {
            "vt_symbol": segments_data["vt_symbol"],
            "summary": intro.get("主营业务"),
            "business_scope": intro.get("经营范围"),
            "main_products": main_products,
            "segments": latest_segments[:30],
            "report_date": latest_report_date,
            "company": {"raw_intro": intro} if intro else {},
            "business_tags": main_products[:6],
            "source": "akshare.stock_zygc_em,akshare.stock_zyjs_ths" if intro else "akshare.stock_zygc_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_sectors(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Return stock sector labels from real stock-board data."""

        normalized = normalize_exchange(symbol, exchange)
        key = f"stock_sectors:{symbol}:{normalized}"
        return market_cache.get_or_set(key, SECTOR_TTL_SECONDS, lambda: self._stock_sectors_uncached(symbol, normalized))

    def _stock_sectors_uncached(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        normalized = normalize_exchange(symbol, exchange)
        items = self._stock_sector_memberships(symbol, normalized)
        source = ",".join(_dedupe_strings([str(item.get("source") or "") for item in items])) or "unavailable"
        return {
            "vt_symbol": vt_symbol(symbol, normalized),
            "items": _dedupe_sector_items(items),
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def list_sectors(self, sector_type: str = "") -> dict[str, Any]:
        """Return AkShare board names."""

        key = f"list_sectors:{sector_type.strip().lower()}"
        return market_cache.get_or_set(key, SECTOR_TTL_SECONDS, lambda: self._list_sectors_uncached(sector_type))

    def search_boards(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Search real EastMoney board symbols without loading the full board tree."""

        key = f"search_boards:{query.strip().lower()}:{limit}"
        return market_cache.get_or_set(key, SECTOR_TTL_SECONDS, lambda: self._search_boards_uncached(query, limit))

    def _search_boards_uncached(self, query: str, limit: int = 20) -> dict[str, Any]:
        items = _eastmoney_search_board_items(query, limit=limit)
        return {
            "query": query,
            "items": items,
            "total": len(items),
            "source": "eastmoney.searchapi.board",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _list_sectors_uncached(self, sector_type: str = "") -> dict[str, Any]:
        requested_type = _normalize_sector_query_type(sector_type)
        if requested_type in {"concept", "theme"}:
            return self.board_names(requested_type, limit=1000)
        if requested_type in {"industry", ""}:
            return self.board_names("industry", limit=500)
        if requested_type == "region":
            return {
                "items": [],
                "type": "region",
                "status": "unavailable",
                "message": "当前主数据源东方财富未提供可稳定访问的地域板块列表。",
                "source": "eastmoney.board",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        return {"items": [], "type": requested_type, "source": "akshare", "updated_at": datetime.now(timezone.utc).isoformat()}

    def sector_stocks(
        self,
        sector_id: str,
        page: int = 1,
        page_size: int = 50,
        sort: str = "changepercent",
        with_returns: bool = False,
        q: str = "",
    ) -> dict[str, Any]:
        """Return AkShare board constituents."""

        key = f"sector_stocks:{sector_id}:{page}:{page_size}:{sort.strip().lower()}:{with_returns}:{q.strip().lower()}"
        ttl = BARS_TTL_SECONDS if with_returns else QUOTE_TTL_SECONDS
        return market_cache.get_or_set(
            key,
            ttl,
            lambda: self._sector_stocks_uncached(sector_id, page, page_size, sort, with_returns, q),
        )

    def _sector_stocks_uncached(
        self,
        sector_id: str,
        page: int = 1,
        page_size: int = 50,
        sort: str = "changepercent",
        with_returns: bool = False,
        q: str = "",
    ) -> dict[str, Any]:
        board_type, symbol = _parse_akshare_sector_id(sector_id)
        query = q.strip().lower()
        if query:
            data = self.board_members(board_type, symbol, limit=500, page=1, sort=sort)
        else:
            data = self.board_members(board_type, symbol, limit=page_size, page=page, sort=sort)
        items = data.get("items") or []
        filtered_total: int | None = None
        if query:
            items = [
                item
                for item in items
                if query in str(item.get("symbol") or "").lower()
                or query in str(item.get("name") or "").lower()
                or query in str(item.get("vt_symbol") or "").lower()
            ]
            filtered_total = len(items)
            start = (max(page, 1) - 1) * min(max(page_size, 1), 100)
            items = items[start : start + min(max(page_size, 1), 100)]
        if with_returns:
            items = self._attach_period_returns(items)
        return {
            "sector_id": sector_id,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": filtered_total if query else data.get("total"),
            "source": data.get("source"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _attach_period_returns(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        enriched = [_ensure_return_keys(item) for item in items]
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="sector-returns") as executor:
            futures = {
                executor.submit(self._stock_period_returns, item): index
                for index, item in enumerate(enriched[:50])
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    returns = future.result()
                except Exception:
                    continue
                enriched[index] = {**enriched[index], **returns}
        return enriched

    def _stock_period_returns(self, item: dict[str, Any]) -> dict[str, float | None]:
        symbol = str(item.get("symbol") or "")
        exchange = str(item.get("exchange") or "")
        if not symbol:
            return {"return_5d": None, "return_10d": None, "return_20d": None}
        bars = self.stock_bars(symbol, exchange, limit=30, interval="1d")
        return _period_returns_from_bars(bars.get("items") or [], (5, 10, 20))

    def sector_trend(self, sector_id: str, page_size: int = 100, pages: int = 3) -> dict[str, Any]:
        """Compute board breadth from AkShare board constituents."""

        key = f"sector_trend:{sector_id}:{page_size}:{pages}"
        return market_cache.get_or_set(key, QUOTE_TTL_SECONDS, lambda: self._sector_trend_uncached(sector_id, page_size, pages))

    def _sector_trend_uncached(self, sector_id: str, page_size: int = 100, pages: int = 3) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        source = "akshare"
        for page in range(1, min(max(pages, 1), 5) + 1):
            data = self.sector_stocks(sector_id, page=page, page_size=page_size)
            source = str(data.get("source") or source)
            rows = data.get("items") or []
            items.extend(rows)
            if len(rows) < page_size:
                break
        return _sector_trend_from_items(sector_id, items, source)

    def stock_industry_chain(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Return industry-chain clues using AkShare business composition."""

        normalized = normalize_exchange(symbol, exchange)
        key = f"stock_industry_chain:{symbol}:{normalized}"
        return market_cache.get_or_set(
            key,
            BUSINESS_TTL_SECONDS,
            lambda: self.stock_industry_chain_from_data(symbol, normalized, self.stock_business(symbol, normalized), self.stock_sectors(symbol, normalized).get("items", [])),
        )

    def stock_industry_chain_from_data(
        self,
        symbol: str,
        exchange: str | None,
        business: dict[str, Any],
        sectors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return industry-chain clues without reloading business and sector data."""

        main_products = business.get("main_products") or []
        dynamic_terms = _dedupe_strings(
            [
                *(sector.get("name") for sector in sectors if sector.get("name")),
                *main_products,
            ]
        )
        return {
            "vt_symbol": vt_symbol(symbol, normalize_exchange(symbol, exchange)),
            "chain_name": " / ".join(dynamic_terms[:2]) if dynamic_terms else None,
            "position": sectors[0].get("name") if sectors else None,
            "upstream": [],
            "midstream": dynamic_terms[:16],
            "downstream": [],
            "exposure": business.get("segments") or [],
            "sectors": sectors,
            "evidence": [{"keyword": item, "source": "akshare.stock_zygc_em"} for item in main_products[:8]],
            "status": "partial" if main_products or sectors else "pending",
            "matched_by": dynamic_terms[:8],
            "source": "akshare.stock_zygc_em,akshare.stock_zyjs_ths,akshare.stock_classify_sina",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def source_status(self) -> list[DataSourceStatus]:
        """Probe AkShare runtime sources."""

        return market_cache.get_or_set("source_status", SOURCE_STATUS_TTL_SECONDS, self._source_status_uncached)

    def _source_status_uncached(self) -> list[DataSourceStatus]:
        now = datetime.now(timezone.utc)
        checks = [
            ("akshare_source_tree", self.info),
            ("akshare_stock_spot", lambda: self.list_stocks(page=1, page_size=1)),
            ("akshare_index_kline", lambda: self._source_status_index_bars(limit=2)),
            ("akshare_stock_kline", lambda: self._probe_stock_bars(limit=2)),
            ("akshare_business_segments", lambda: self._probe_business_segments(limit=1)),
            ("akshare_concept_boards", lambda: self.board_names("concept", limit=1)),
            ("akshare_industry_boards", lambda: self.board_names("industry", limit=1)),
        ]

        def run(fn) -> tuple[bool, str]:
            try:
                fn()
                return True, "ok"
            except Exception as exc:
                return False, exc.__class__.__name__

        # 外网探测并行执行：总耗时 = 最慢一路（原串行为 7 路累加，冷缓存 3-10s）
        with ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="source-status") as pool:
            results = list(pool.map(lambda item: run(item[1]), checks))
        return [
            DataSourceStatus(name=name, ok=ok, message=message, checked_at=now)
            for (name, _), (ok, message) in zip(checks, results, strict=True)
        ]

    def _source_status_index_bars(self, limit: int = 2) -> dict[str, Any]:
        indices = [quote.to_api() for quote in self.get_indices()]
        index = _first_payload_item({"items": indices})
        symbol = str(index.get("symbol") or "")
        exchange = str(index.get("exchange") or "")
        if not symbol:
            raise AkShareSourceError("No sample index returned by live index quotes")
        return self.stock_bars(symbol, exchange, limit=limit, interval="1d")

    def _stock_bars(
        self,
        symbol: str,
        interval: str,
        limit: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[pd.DataFrame, str]:
        normalized_exchange = normalize_exchange(symbol)
        prefixed = _prefixed_symbol(symbol, normalized_exchange)
        if interval in {"1m", "5m", "15m", "30m", "60m"}:
            if not start_date and not end_date:
                try:
                    module = importlib.import_module("akshare.stock.stock_zh_a_sina")
                    with _akshare_network_env():
                        df = module.stock_zh_a_minute(symbol=prefixed, period=interval.removesuffix("m"), adjust="")
                    if not df.empty:
                        return df.tail(limit), "akshare.stock_zh_a_minute"
                except Exception:
                    pass
            df = _eastmoney_stock_kline(symbol, normalized_exchange, interval, limit, start_date, end_date)
            return df.tail(limit), "eastmoney.stock_kline_minute"

        # 日线优先 tencent_full:实测最快(~0.1s/股)且 OHLC/volume 与 akshare 逐位一致。
        # 仅当其返回的最早日期能覆盖 start_date 时采用;长历史回填时过滤后覆盖不足,
        # 自动 fallback 到 eastmoney/akshare,避免漏掉 start_date 到近期之间的数据。
        try:
            df = _tencent_stock_kline_full(symbol, normalized_exchange, interval, max(limit, 5))
            if not df.empty:
                earliest = str(df["date"].min())
                if not start_date or earliest <= _date_key(start_date):
                    return df.tail(limit), "tencent.stock_kline_full"
        except Exception:
            pass

        try:
            df = _eastmoney_stock_kline(symbol, normalized_exchange, interval, limit, start_date, end_date)
            if not df.empty:
                return df.tail(limit), "eastmoney.stock_kline"
        except Exception:
            pass

        module = importlib.import_module("akshare.stock_feature.stock_hist_tx")
        start_value = start_date or _history_start_for_limit(limit, interval)
        end_value = end_date or "20500101"
        with _akshare_network_env():
            df = module.stock_zh_a_hist_tx(symbol=prefixed, start_date=start_value, end_date=end_value, adjust="")
        if interval == "1w":
            df = _resample_ohlcv(df, "W")
        elif interval == "1mo":
            df = _resample_ohlcv(df, "ME")
        return df.tail(limit), "akshare.stock_zh_a_hist"

    def _index_bars(self, symbol: str, exchange: str, interval: str, limit: int) -> tuple[pd.DataFrame, str]:
        if interval in {"1m", "5m", "15m", "30m", "60m"}:
            module = importlib.import_module("akshare.index.index_zh_em")
            with _akshare_network_env():
                df = module.index_zh_a_hist_min_em(symbol=symbol, period=interval.removesuffix("m"))
            return df.tail(limit), "akshare.index_zh_a_hist_min_em"

        try:
            df = _tencent_stock_kline(symbol, exchange, interval, limit)
            if not df.empty:
                return df.tail(limit), "tencent.stock_kline"
        except Exception:
            pass

        try:
            df = _eastmoney_stock_kline(symbol, exchange, interval, limit)
            if not df.empty:
                return df.tail(limit), "eastmoney.stock_kline"
        except Exception:
            pass

        module = importlib.import_module("akshare.stock_feature.stock_hist_tx")
        ak_symbol = _prefixed_symbol(symbol, exchange)
        start_date = _history_start_for_limit(limit, interval)
        with _akshare_network_env():
            df = module.stock_zh_a_hist_tx(symbol=ak_symbol, start_date=start_date, end_date="20500101", adjust="")
        if interval == "1w":
            df = _resample_ohlcv(df, "W")
        elif interval == "1mo":
            df = _resample_ohlcv(df, "ME")
        return df.tail(limit), "akshare.stock_zh_a_hist_tx"

    def _stock_individual_info(self, symbol: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock.stock_info_em")
        with _akshare_network_env():
            df = module.stock_individual_info_em(symbol=symbol)
        return {str(row["item"]): _json_value(row["value"]) for row in df.to_dict(orient="records")}

    def _with_period_returns(self, item: dict[str, Any]) -> dict[str, Any]:
        if all(key in item and item.get(key) is not None for key in ("return_5d", "return_10d", "return_20d")):
            return item
        symbol = str(item.get("symbol") or "")
        exchange = str(item.get("exchange") or "")
        returns = {"return_5d": None, "return_10d": None, "return_20d": None}
        try:
            bars = self.stock_bars(symbol, exchange, limit=25, interval="1d").get("items", [])
            returns.update(_period_returns_from_bars(bars, (5, 10, 20)))
        except Exception:
            pass
        return {**item, **returns}

    def _all_stock_spot_rows(self) -> list[dict[str, Any]]:
        return market_cache.get_or_set("all_stock_spot_rows", FULL_LIST_TTL_SECONDS, self._all_stock_spot_rows_uncached)

    def _all_stock_spot_rows_uncached(self) -> list[dict[str, Any]]:
        module = importlib.import_module("akshare.stock.stock_zh_a_tx")
        with _akshare_network_env():
            df, total = _stock_zh_a_spot_tx_page(module, offset=0, count=200, sort="price")
            rows = _all_records(df)
            page = 1
            while total and len(rows) < total and page < 40:
                df, _ = _stock_zh_a_spot_tx_page(module, offset=page * 200, count=200, sort="price")
                page_rows = _all_records(df)
                if not page_rows:
                    break
                rows.extend(page_rows)
                page += 1
        return rows

    def _stock_sector_memberships(self, symbol: str, exchange: str | None = None) -> list[dict[str, Any]]:
        normalized = normalize_exchange(symbol, exchange)
        try:
            hsf10_items = _eastmoney_hsf10_stock_sectors(symbol, normalized)
        except Exception:
            hsf10_items = []
        if hsf10_items:
            return hsf10_items

        text = self._stock_business_text(symbol)
        candidates = _candidate_sectors_for_text(text)
        return [
            {
                **sector,
                "confirmed": False,
                "confirmation": "candidate_from_akshare_business_text",
                "source": "akshare.stock_classify_sina,akshare.stock_zyjs_ths,akshare.stock_zygc_em",
            }
            for sector in candidates[:12]
        ]

    def _stock_business_text(self, symbol: str) -> str:
        parts: list[str] = []
        try:
            business = self.stock_business(symbol)
            parts.extend(str(item) for item in business.get("main_products") or [] if item)
            parts.extend(
                str(segment.get("name"))
                for segment in business.get("segments") or []
                if segment.get("name")
            )
            if business.get("business_scope"):
                parts.append(str(business["business_scope"]))
            if business.get("summary"):
                parts.append(str(business["summary"]))
        except Exception:
            pass
        try:
            intro = self._stock_business_intro(symbol)
            parts.extend(str(value) for value in intro.values() if value)
        except Exception:
            pass
        return " ".join(parts)

    def _trade_date_from_quotes(self, quotes: list[Quote]) -> date:
        for quote in quotes:
            if quote.trade_time:
                try:
                    return date.fromisoformat(str(quote.trade_time)[:10])
                except ValueError:
                    pass
        today = date.today()
        while today.weekday() >= 5:
            today -= timedelta(days=1)
        return today

    def board_names(self, board_type: str = "concept", limit: int = 20) -> dict[str, Any]:
        """Return real concept, industry, theme, or region board rows through AkShare."""

        key = f"board_names:{board_type.strip().lower()}:{limit}"
        return market_cache.get_or_set(key, SECTOR_TTL_SECONDS, lambda: self._board_names_uncached(board_type, limit))

    def live_board_quotes(
        self,
        board_type: str = "concept",
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Return a short-lived board quote snapshot for intraday decisions."""

        normalized_type = board_type.strip().lower()
        bounded_limit = min(max(int(limit), 1), 1000)
        key = f"live_board_quotes:{normalized_type}:{bounded_limit}"
        return market_cache.get_or_set(
            key,
            QUOTE_TTL_SECONDS,
            lambda: self._board_names_uncached(normalized_type, bounded_limit),
        )

    def _board_names_uncached(self, board_type: str = "concept", limit: int = 20) -> dict[str, Any]:
        normalized_type = _normalize_board_type(board_type)
        items: list[dict[str, Any]]
        source = "eastmoney.board"
        if normalized_type in {"concept", "theme", "industry"}:
            items = _eastmoney_board_items(normalized_type)
        elif normalized_type == "region":
            items = []
            source = "unavailable"
        else:
            items = []

        if not items and normalized_type in {"concept", "theme", "industry", "region"}:
            items = _sina_sector_items(normalized_type)
            source = "akshare.stock_classify_sina"

        bounded_limit = min(max(limit, 1), 1000)
        return {
            "items": items[:bounded_limit],
            "total": len(items),
            "type": normalized_type,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def board_members(
        self,
        board_type: str,
        symbol: str,
        limit: int = 100,
        page: int = 1,
        sort: str = "changepercent",
    ) -> dict[str, Any]:
        """Return real board constituents by AkShare/Sina board name or node code."""

        key = f"board_members:{board_type.strip().lower()}:{symbol}:{limit}:{page}:{sort.strip().lower()}"
        return market_cache.get_or_set(key, QUOTE_TTL_SECONDS, lambda: self._board_members_uncached(board_type, symbol, limit, page, sort))

    def _board_members_uncached(
        self,
        board_type: str,
        symbol: str,
        limit: int = 100,
        page: int = 1,
        sort: str = "changepercent",
    ) -> dict[str, Any]:
        normalized_type = _normalize_board_type(board_type)
        if _is_eastmoney_board_symbol(symbol) or normalized_type in {"concept", "theme", "industry"}:
            try:
                return _eastmoney_board_members(normalized_type, symbol, limit=limit, page=page, sort=sort)
            except Exception:
                if _is_eastmoney_board_symbol(symbol):
                    raise

        bounded_limit = min(max(limit, 1), 500)
        sector = _resolve_sina_sector(normalized_type, symbol)
        with _akshare_network_env():
            total = _sina_sector_member_count(sector["id"])
            rows = _sina_sector_member_rows(sector["id"], page=max(page, 1), page_size=bounded_limit, sort=sort)
        items = [_sina_member_row_to_api(row) for row in rows]
        return {
            "items": items,
            "total": total,
            "type": normalized_type,
            "symbol": sector["id"],
            "sector": sector,
            "source": "akshare.stock_classify_sina",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_news(self, symbol: str, limit: int = 10) -> dict[str, Any]:
        """Return real EastMoney stock news through AkShare."""

        return market_cache.get_or_set(f"stock_news:{symbol}:{limit}", BARS_TTL_SECONDS, lambda: self._stock_news_uncached(symbol, limit))

    def _stock_news_uncached(self, symbol: str, limit: int = 10) -> dict[str, Any]:
        module = importlib.import_module("akshare.news.news_stock")
        with _akshare_network_env():
            df = module.stock_news_em(symbol=symbol)
        return {
            "items": [_normalize_record(row) for row in _records(df, limit)],
            "total": len(df),
            "symbol": symbol,
            "source": "akshare.stock_news_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_business_segments(self, symbol: str, exchange: str | None = None, limit: int = 30) -> dict[str, Any]:
        """Return real business composition rows through AkShare."""

        normalized_exchange = normalize_exchange(symbol, exchange)
        key = f"stock_business_segments:{symbol}:{normalized_exchange}:{limit}"
        return market_cache.get_or_set(
            key,
            BUSINESS_TTL_SECONDS,
            lambda: self._stock_business_segments_uncached(symbol, normalized_exchange, limit),
        )

    def _stock_business_segments_uncached(self, symbol: str, exchange: str | None = None, limit: int = 30) -> dict[str, Any]:
        normalized_exchange = normalize_exchange(symbol, exchange)
        ak_symbol = _eastmoney_secucode(symbol, normalized_exchange)
        module = importlib.import_module("akshare.stock_fundamental.stock_zygc")
        with _akshare_network_env():
            df = module.stock_zygc_em(symbol=ak_symbol)
        return {
            "items": [_normalize_record(row) for row in _records(df, limit)],
            "total": len(df),
            "symbol": symbol,
            "exchange": normalized_exchange,
            "vt_symbol": vt_symbol(symbol, normalized_exchange),
            "akshare_symbol": ak_symbol,
            "source": "akshare.stock_zygc_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _stock_business_intro(self, symbol: str) -> dict[str, Any]:
        return market_cache.get_or_set(f"stock_business_intro:{symbol}", BUSINESS_TTL_SECONDS, lambda: self._stock_business_intro_uncached(symbol))

    def _stock_business_intro_uncached(self, symbol: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_fundamental.stock_zyjs_ths")
        with _akshare_network_env():
            df = module.stock_zyjs_ths(symbol=symbol)
        rows = _all_records(df)
        return rows[0] if rows else {}

    # ── Shenwan Industry Classification ──

    def shenwan_industry_tree(self, level: int = 1) -> dict[str, Any]:
        """Return Shenwan industry classification tree for the given level (1/2/3)."""

        bounded_level = min(max(level, 1), 3)
        key = f"shenwan_industry_tree:{bounded_level}"
        return market_cache.get_or_set(key, SW_TREE_TTL_SECONDS, lambda: self._shenwan_industry_tree_uncached(bounded_level))

    def _shenwan_industry_tree_uncached(self, level: int) -> dict[str, Any]:
        func_map = {1: "sw_index_first_info", 2: "sw_index_second_info", 3: "sw_index_third_info"}
        func_name = func_map.get(level)
        if not func_name:
            return {"items": [], "level": level, "source": "akshare.sw_index", "status": "invalid_level"}
        try:
            module = importlib.import_module("akshare.stock_industry")
        except ImportError:
            module = importlib.import_module("akshare.index.index_sw")
        func = getattr(module, func_name, None)
        if func is None:
            return {"items": [], "level": level, "source": "akshare.sw_index", "status": "function_not_found"}
        with _akshare_network_env():
            df = func()
        items = []
        for row in _all_records(df):
            code = str(row.get("行业代码") or row.get("板块代码") or row.get("index_code") or "")
            name = str(row.get("行业名称") or row.get("板块名称") or row.get("index_name") or "")
            if not code or not name:
                continue
            parent_name = str(row.get("上一级行业") or row.get("parent_name") or "") or None
            items.append({
                "code": code,
                "name": name,
                "level": level,
                "parent_name": parent_name,
                "stock_count": _number(row.get("股票数量") or row.get("stock_count")),
                "pe_ttm": _number(row.get("市盈率") or row.get("pe_ttm")),
                "pb": _number(row.get("市净率") or row.get("pb")),
                "dividend_yield": _number(row.get("股息率") or row.get("dividend_yield")),
            })
        return {
            "items": items,
            "level": level,
            "total": len(items),
            "source": "akshare.sw_index",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def shenwan_industry_constituents(self, industry_code: str) -> dict[str, Any]:
        """Return constituent stocks for a Shenwan industry (level 3)."""

        key = f"shenwan_industry_constituents:{industry_code}"
        return market_cache.get_or_set(key, SW_CONSTITUENTS_TTL_SECONDS, lambda: self._shenwan_industry_constituents_uncached(industry_code))

    def _shenwan_industry_constituents_uncached(self, industry_code: str) -> dict[str, Any]:
        try:
            module = importlib.import_module("akshare.stock_industry")
        except ImportError:
            module = importlib.import_module("akshare.index.index_sw")
        func = getattr(module, "sw_index_third_cons", None)
        if func is None:
            return {"items": [], "industry_code": industry_code, "source": "akshare.sw_index", "status": "function_not_found"}
        with _akshare_network_env():
            df = func(symbol=industry_code)
        items = []
        for row in _all_records(df):
            symbol = str(row.get("股票代码") or row.get("code") or "")
            name = str(row.get("股票名称") or row.get("name") or "")
            if not symbol or not name:
                continue
            exchange = normalize_exchange(symbol)
            items.append({
                "symbol": symbol,
                "name": name,
                "exchange": exchange,
                "vt_symbol": vt_symbol(symbol, exchange),
                "market_cap": _number(row.get("总市值") or row.get("market_cap")),
                "change_pct": _number(row.get("涨跌幅") or row.get("change_pct")),
            })
        return {
            "items": items,
            "industry_code": industry_code,
            "total": len(items),
            "source": "akshare.sw_index",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def shenwan_stock_classification(self, symbol: str) -> dict[str, Any]:
        """Return the Shenwan industry classification for a single stock."""

        key = f"shenwan_stock_classification:{symbol.strip()}"
        return market_cache.get_or_set(key, SW_CLASSIFY_TTL_SECONDS, lambda: self._shenwan_stock_classification_uncached(symbol))

    def _shenwan_stock_classification_uncached(self, symbol: str) -> dict[str, Any]:
        clean_symbol = symbol.strip()
        try:
            module = importlib.import_module("akshare.stock_industry")
        except ImportError:
            module = importlib.import_module("akshare.stock.stock_industry_sw")
        func = getattr(module, "stock_industry_clf_hist_sw", None)
        if func is None:
            return {"vt_symbol": clean_symbol, "levels": {}, "source": "akshare", "status": "function_not_found"}
        with _akshare_network_env():
            df = func(stock_code=clean_symbol)
        levels: dict[str, Any] = {}
        for row in _all_records(df):
            stage = str(row.get("行业分级") or "")
            code = str(row.get("行业代码") or "")
            name = str(row.get("行业名称") or "")
            if not code or not name:
                continue
            if "一" in stage or stage == "1":
                levels["level1"] = {"code": code, "name": name}
            elif "二" in stage or stage == "2":
                levels["level2"] = {"code": code, "name": name}
            elif "三" in stage or stage == "3":
                levels["level3"] = {"code": code, "name": name}
        exchange = normalize_exchange(clean_symbol)
        return {
            "vt_symbol": vt_symbol(clean_symbol, exchange),
            "levels": levels,
            "source": "akshare.stock_industry_sw",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def shenwan_industry_realtime(self) -> dict[str, Any]:
        """Return EastMoney industry board realtime data for enriching Shenwan industries."""

        key = "shenwan_industry_realtime"
        return market_cache.get_or_set(key, QUOTE_TTL_SECONDS, self._shenwan_industry_realtime_uncached)

    def _shenwan_industry_realtime_uncached(self) -> dict[str, Any]:
        try:
            items = _eastmoney_board_items("industry")
        except Exception:
            items = []
        return {
            "items": items,
            "total": len(items),
            "source": "eastmoney.push2.board",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Research data methods (sector dashboard + stock workbench) ──

    SECTOR_BARS_TTL_SECONDS = 86400
    FUND_FLOW_TTL_SECONDS = 60
    LIMIT_POOL_TTL_SECONDS = 600
    LIVE_LIMIT_POOL_TTL_SECONDS = 20
    LHB_TTL_SECONDS = 86400
    HOT_RANK_TTL_SECONDS = 300
    FINANCIAL_TTL_SECONDS = 86400 * 3

    def sector_daily_bars(
        self,
        sector_id: str,
        board_type: str = "concept",
        limit: int = SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS,
    ) -> dict[str, Any]:
        """Return sector/board historical K-lines through AkShare EastMoney board hist."""

        history_limit = min(
            max(int(limit), 1),
            SECTOR_DAILY_MAX_HISTORY_SESSIONS,
        )
        key = f"sector_daily_bars:{sector_id}:{board_type}:{history_limit}"
        return market_cache.get_or_set(
            key,
            self.SECTOR_BARS_TTL_SECONDS,
            lambda: self._sector_daily_bars_uncached(
                sector_id,
                board_type,
                history_limit,
            ),
        )

    def _sector_daily_bars_uncached(
        self,
        sector_id: str,
        board_type: str,
        limit: int,
    ) -> dict[str, Any]:
        normalized_type = _normalize_board_type(board_type)
        # Resolve board name for AkShare API (needs the name, not BK code)
        board_name = sector_id
        try:
            board = _resolve_eastmoney_board(normalized_type, sector_id)
            board_name = str(board.get("name") or sector_id)
        except Exception:
            pass

        start_date_str = (date.today() - timedelta(days=max(limit * 2, 500))).strftime("%Y%m%d")
        end_date_str = date.today().strftime("%Y%m%d")
        try:
            df = _eastmoney_board_kline(sector_id, normalized_type, limit, start_date_str, end_date_str)
            source = "eastmoney.board_kline"
        except Exception as eastmoney_exc:
            logger.debug("eastmoney board kline failed for %s: %s", sector_id, eastmoney_exc)
            try:
                df = _eastmoney_board_daily_quote(sector_id)
                source = "eastmoney.board_kline"
            except Exception as quote_exc:
                logger.debug(
                    "eastmoney board daily quote failed for %s: %s",
                    sector_id,
                    quote_exc,
                )
                df, source = self._sector_daily_bars_ths(
                    board_name,
                    normalized_type,
                    start_date_str,
                    end_date_str,
                )

        items = [
            _sector_bar_row_to_api(row)
            for row in _tail_records(df, limit)
        ]
        return {
            "sector_id": sector_id,
            "board_type": normalized_type,
            "items": items,
            "total": len(items),
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _sector_daily_bars_ths(
        self,
        board_name: str,
        normalized_type: str,
        start_date_str: str,
        end_date_str: str,
    ) -> tuple[pd.DataFrame, str]:
        if normalized_type in {"concept", "theme"}:
            module = importlib.import_module("akshare.stock_feature.stock_board_concept_ths")
            with _akshare_network_env():
                df = module.stock_board_concept_index_ths(
                    symbol=board_name,
                    start_date=start_date_str,
                    end_date=end_date_str,
                )
            source = "akshare.stock_board_concept_index_ths"
        else:
            module = importlib.import_module("akshare.stock_feature.stock_board_industry_ths")
            with _akshare_network_env():
                df = module.stock_board_industry_index_ths(
                    symbol=board_name,
                    start_date=start_date_str,
                    end_date=end_date_str,
                )
            source = "akshare.stock_board_industry_index_ths"
        return df, source

    def sector_fund_flows(
        self,
        sector_type: str = "concept",
        period: str = "即时",
    ) -> dict[str, Any]:
        """Return sector-level fund flow data through AkShare."""

        key = f"sector_fund_flows:{sector_type}:{period}"
        return market_cache.get_or_set(
            key,
            self.FUND_FLOW_TTL_SECONDS,
            lambda: self._sector_fund_flows_uncached(sector_type, period),
        )

    def _sector_fund_flows_uncached(self, sector_type: str, period: str) -> dict[str, Any]:
        normalized_type = _normalize_board_type(sector_type)
        df = _eastmoney_sector_fund_flow(normalized_type, period)
        items = [_fund_flow_row_to_api(row) for row in _records(df, 500)]
        return {
            "sector_type": normalized_type,
            "period": period,
            "items": items,
            "total": len(items),
            "source": "eastmoney.sector_fund_flow_rank",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_fund_flows(
        self,
        symbol: str,
        exchange: str | None = None,
        period: str = "即时",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return individual stock fund flow through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        key = f"stock_fund_flows:{symbol}:{normalized}:{period}:{limit}"
        return market_cache.get_or_set(
            key,
            self.FUND_FLOW_TTL_SECONDS,
            lambda: self._stock_fund_flows_uncached(symbol, normalized, period, limit),
        )

    def _stock_fund_flows_uncached(self, symbol: str, exchange: str, period: str, limit: int) -> dict[str, Any]:
        bounded_limit = min(max(int(limit or 50), 1), 5000)
        try:
            df, source = self._stock_main_fund_flow(period)
        except Exception:
            df, source = self._stock_ths_fund_flow(period)

        target = symbol.strip()
        code_column = _first_existing_column(df, ("代码", "股票代码", "code"))
        if target and code_column and not df.empty:
            matched = df[df[code_column].astype(str).str.strip().str.endswith(target)]
        else:
            matched = df
        items = [_stock_fund_flow_row_to_api(row, symbol) for row in _records(matched, bounded_limit)]
        if not items:
            items = [_stock_fund_flow_row_to_api(row, symbol) for row in _records(df, bounded_limit)]
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "period": period,
            "items": items,
            "total": len(items),
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _stock_main_fund_flow(self, period: str) -> tuple[pd.DataFrame, str]:
        """Fetch EastMoney main-fund ranking for batch stock fund-flow sync."""

        del period
        return _eastmoney_stock_main_fund_flow(limit=500), "eastmoney.stock_main_fund_flow"

    def _stock_ths_fund_flow(self, period: str) -> tuple[pd.DataFrame, str]:
        """Fallback to THS fund-flow table when EastMoney ranking is unavailable."""

        module = importlib.import_module("akshare.stock_feature.stock_fund_flow")
        with _akshare_network_env():
            df = module.stock_fund_flow_individual(symbol=period)
        return df, "akshare.stock_fund_flow_individual"

    def limit_up_pools(self, trade_date: str | None = None) -> dict[str, Any]:
        """Return limit-up, limit-down and related pools through AkShare."""

        if trade_date is None:
            trade_date = date.today().strftime("%Y%m%d")
        trade_date = str(trade_date).replace("-", "")[:8]
        ttl_seconds = (
            self.LIVE_LIMIT_POOL_TTL_SECONDS
            if trade_date == date.today().strftime("%Y%m%d")
            else self.LIMIT_POOL_TTL_SECONDS
        )
        key = f"limit_up_pools:{trade_date}"
        return market_cache.get_or_set(
            key,
            ttl_seconds,
            lambda: self._limit_up_pools_uncached(trade_date),
        )

    def _limit_up_pools_uncached(self, trade_date: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_feature.stock_ztb_em")
        pools: dict[str, Any] = {"trade_date": trade_date, "pools": {}}
        pool_configs = [
            ("zt", "stock_zt_pool_em", "涨停池"),
            ("zt_previous", "stock_zt_pool_previous_em", "昨日涨停"),
            ("strong", "stock_zt_pool_strong_em", "强势股"),
            ("zbgc", "stock_zt_pool_zbgc_em", "炸板池"),
            ("dtgc", "stock_zt_pool_dtgc_em", "跌停池"),
        ]
        futures: dict[Any, tuple[str, str]] = {}
        with _akshare_network_env(), ThreadPoolExecutor(
            max_workers=len(pool_configs)
        ) as executor:
            for pool_key, func_name, pool_label in pool_configs:
                func = getattr(module, func_name, None)
                if func is None:
                    pools["pools"][pool_key] = {
                        "label": pool_label,
                        "items": [],
                        "total": 0,
                        "status": "unavailable",
                    }
                    continue
                futures[executor.submit(func, date=trade_date)] = (
                    pool_key,
                    pool_label,
                )

            for future in as_completed(futures):
                pool_key, pool_label = futures[future]
                try:
                    df = future.result()
                    pools["pools"][pool_key] = {
                        "label": pool_label,
                        "items": [_zt_pool_row_to_api(row) for row in _records(df, 200)],
                        "total": len(df),
                    }
                except Exception:
                    pools["pools"][pool_key] = {
                        "label": pool_label,
                        "items": [],
                        "total": 0,
                        "status": "unavailable",
                    }
        pools["source"] = "akshare.stock_ztb_em"
        pools["updated_at"] = datetime.now(timezone.utc).isoformat()
        return pools

    def stock_hot_ranks(self, limit: int = 100) -> dict[str, Any]:
        """Return stock hot rank list through AkShare."""

        key = f"stock_hot_ranks:{limit}"
        return market_cache.get_or_set(
            key,
            self.HOT_RANK_TTL_SECONDS,
            lambda: self._stock_hot_ranks_uncached(limit),
        )

    def _stock_hot_ranks_uncached(self, limit: int) -> dict[str, Any]:
        items = _eastmoney_stock_hot_rank_items(limit)
        return {
            "items": items,
            "total": len(items),
            "source": "eastmoney.stockrank",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_hot_detail(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """Return stock hot rank detail and keywords through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        ak_symbol = _eastmoney_secucode(symbol, normalized)
        key = f"stock_hot_detail:{ak_symbol}"
        return market_cache.get_or_set(
            key,
            self.HOT_RANK_TTL_SECONDS,
            lambda: self._stock_hot_detail_uncached(ak_symbol, symbol, normalized),
        )

    def _stock_hot_detail_uncached(self, ak_symbol: str, symbol: str, exchange: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock.stock_hot_rank_em")
        rank, keywords = None, []
        try:
            with _akshare_network_env():
                df = module.stock_hot_rank_detail_em(symbol=ak_symbol)
            rows = _records(df, 10)
            if rows:
                rank = _number(rows[0].get("当前排名"))
        except Exception:
            pass
        try:
            with _akshare_network_env():
                df = module.stock_hot_keyword_em(symbol=ak_symbol)
            keywords = [str(row.get("关键词") or row.get("keyword") or "") for row in _records(df, 10)]
            keywords = [k for k in keywords if k]
        except Exception:
            pass
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "rank": rank,
            "keywords": keywords,
            "source": "akshare.stock_hot_rank_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_lhb_records(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return dragon-tiger list (龙虎榜) records through AkShare."""

        if start_date is None:
            start_date = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
        if end_date is None:
            end_date = date.today().strftime("%Y%m%d")
        key = f"stock_lhb_records:{start_date}:{end_date}"
        return market_cache.get_or_set(
            key,
            self.LHB_TTL_SECONDS,
            lambda: self._stock_lhb_records_uncached(start_date, end_date),
        )

    def _stock_lhb_records_uncached(self, start_date: str, end_date: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_feature.stock_lhb_em")
        with _akshare_network_env():
            df = module.stock_lhb_detail_em(
                start_date=start_date,
                end_date=end_date,
            )
        items = [_lhb_row_to_api(row) for row in _records(df, 500)]
        return {
            "start_date": start_date,
            "end_date": end_date,
            "items": items,
            "total": len(df),
            "source": "akshare.stock_lhb_detail_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_notices(
        self,
        symbol: str,
        date_str: str | None = None,
    ) -> dict[str, Any]:
        """Return stock notice/announcement data through AkShare."""

        key = f"stock_notices:{symbol}:{date_str or 'latest'}"
        return market_cache.get_or_set(
            key,
            self.FINANCIAL_TTL_SECONDS,
            lambda: self._stock_notices_uncached(symbol, date_str),
        )

    def _stock_notices_uncached(self, symbol: str, date_str: str | None) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_fundamental.stock_notice")
        kwargs: dict[str, Any] = {}
        if date_str:
            kwargs["date"] = date_str
        with _akshare_network_env():
            df = module.stock_notice_report(**kwargs)
        # Filter for this symbol if available
        target = symbol.strip()
        if "代码" in df.columns and not df.empty:
            df = df[df["代码"].astype(str).str.strip() == target]
        items = [_notice_row_to_api(row) for row in _records(df, 50)]
        return {
            "symbol": symbol,
            "items": items,
            "total": len(items),
            "source": "akshare.stock_notice_report",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_financial_quarterly(
        self,
        symbol: str,
        exchange: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return quarterly profit sheet data through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        ak_symbol = _eastmoney_secucode(symbol, normalized)
        key = f"stock_financial_quarterly:{ak_symbol}:{limit}"
        return market_cache.get_or_set(
            key,
            self.FINANCIAL_TTL_SECONDS,
            lambda: self._stock_financial_quarterly_uncached(ak_symbol, symbol, normalized, limit),
        )

    def _stock_financial_quarterly_uncached(
        self,
        ak_symbol: str,
        symbol: str,
        exchange: str,
        limit: int,
    ) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_feature.stock_three_report_em")
        with _akshare_network_env():
            df = module.stock_profit_sheet_by_quarterly_em(symbol=ak_symbol)
        items = [_financial_row_to_api(row) for row in _records(df, limit)]
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "period_type": "quarterly",
            "items": items,
            "total": len(df),
            "source": "akshare.stock_profit_sheet_by_quarterly_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_financial_performance(
        self,
        report_date: date | datetime | str,
    ) -> dict[str, Any]:
        """Return the market-wide point-in-time performance report for one quarter."""

        normalized_date = _financial_report_date(report_date)
        key = f"stock_financial_performance:{normalized_date}"
        return market_cache.get_or_set(
            key,
            FINANCIAL_PERFORMANCE_TTL_SECONDS,
            lambda: self._stock_financial_performance_uncached(normalized_date),
        )

    def _stock_financial_performance_uncached(
        self,
        report_date: str,
    ) -> dict[str, Any]:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params: dict[str, Any] = {
            "sortColumns": "UPDATE_DATE,SECURITY_CODE",
            "sortTypes": "-1,-1",
            "pageSize": str(FINANCIAL_PERFORMANCE_PAGE_SIZE),
            "pageNumber": "1",
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "ALL",
            "filter": f"(REPORTDATE='{report_date}')",
        }
        rows: list[dict[str, Any]] = []
        page = 1
        pages = 1
        with _akshare_network_env():
            while page <= pages and page <= FINANCIAL_PERFORMANCE_MAX_PAGES:
                params["pageNumber"] = str(page)
                response = requests.get(
                    url,
                    params=params,
                    headers=EASTMONEY_HEADERS,
                    timeout=FINANCIAL_PERFORMANCE_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                result = payload.get("result") if isinstance(payload, Mapping) else None
                if not isinstance(result, Mapping):
                    message = payload.get("message") if isinstance(payload, Mapping) else None
                    raise AkShareSourceError(
                        f"Eastmoney financial performance unavailable for {report_date}: {message or 'empty result'}"
                    )
                raw_rows = result.get("data") or []
                rows.extend(dict(row) for row in raw_rows if isinstance(row, Mapping))
                pages = max(int(result.get("pages") or 1), 1)
                page += 1
        if pages > FINANCIAL_PERFORMANCE_MAX_PAGES:
            raise AkShareSourceError(
                f"Eastmoney financial performance exceeded {FINANCIAL_PERFORMANCE_MAX_PAGES} pages"
            )

        items = [
            item
            for row in rows
            if (item := _financial_performance_row_to_api(row)).get("vt_symbol")
        ]
        return {
            "report_date": report_date,
            "period_type": "quarterly",
            "items": items,
            "total": len(items),
            "source": "eastmoney.RPT_LICO_FN_CPD",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_balance_sheet(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """Return balance sheet through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        ak_symbol = _eastmoney_secucode(symbol, normalized)
        key = f"stock_balance_sheet:{ak_symbol}"
        return market_cache.get_or_set(
            key,
            self.FINANCIAL_TTL_SECONDS,
            lambda: self._stock_balance_sheet_uncached(ak_symbol, symbol, normalized),
        )

    def _stock_balance_sheet_uncached(self, ak_symbol: str, symbol: str, exchange: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_feature.stock_three_report_em")
        with _akshare_network_env():
            df = module.stock_balance_sheet_by_report_em(symbol=ak_symbol)
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "statement_type": "balance_sheet",
            "items": _records(df, 8),
            "total": len(df),
            "source": "akshare.stock_balance_sheet_by_report_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_profit_sheet(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """Return profit/income sheet through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        ak_symbol = _eastmoney_secucode(symbol, normalized)
        key = f"stock_profit_sheet:{ak_symbol}"
        return market_cache.get_or_set(
            key,
            self.FINANCIAL_TTL_SECONDS,
            lambda: self._stock_profit_sheet_uncached(ak_symbol, symbol, normalized),
        )

    def _stock_profit_sheet_uncached(self, ak_symbol: str, symbol: str, exchange: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_feature.stock_three_report_em")
        with _akshare_network_env():
            df = module.stock_profit_sheet_by_report_em(symbol=ak_symbol)
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "statement_type": "profit_sheet",
            "items": _records(df, 8),
            "total": len(df),
            "source": "akshare.stock_profit_sheet_by_report_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_cash_flow_sheet(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """Return cash flow sheet through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        ak_symbol = _eastmoney_secucode(symbol, normalized)
        key = f"stock_cash_flow_sheet:{ak_symbol}"
        return market_cache.get_or_set(
            key,
            self.FINANCIAL_TTL_SECONDS,
            lambda: self._stock_cash_flow_sheet_uncached(ak_symbol, symbol, normalized),
        )

    def _stock_cash_flow_sheet_uncached(self, ak_symbol: str, symbol: str, exchange: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_feature.stock_three_report_em")
        with _akshare_network_env():
            df = module.stock_cash_flow_sheet_by_report_em(symbol=ak_symbol)
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "statement_type": "cash_flow",
            "items": _records(df, 8),
            "total": len(df),
            "source": "akshare.stock_cash_flow_sheet_by_report_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_financial_indicators(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """Return financial analysis indicators through AkShare."""

        normalized = normalize_exchange(symbol, exchange)
        key = f"stock_financial_indicators:{symbol}:{normalized}"
        return market_cache.get_or_set(
            key,
            self.FINANCIAL_TTL_SECONDS,
            lambda: self._stock_financial_indicators_uncached(symbol, normalized),
        )

    def _stock_financial_indicators_uncached(self, symbol: str, exchange: str) -> dict[str, Any]:
        module = importlib.import_module("akshare.stock_fundamental.stock_finance_sina")
        with _akshare_network_env():
            df = module.stock_financial_analysis_indicator_em(symbol=symbol)
        items = [_indicator_row_to_api(row) for row in _records(df, 8)]
        return {
            "vt_symbol": vt_symbol(symbol, exchange),
            "items": items,
            "total": len(df),
            "source": "akshare.stock_financial_analysis_indicator_em",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def stock_business_segments_history(
        self,
        symbol: str,
        exchange: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return business segments across multiple report periods."""

        normalized = normalize_exchange(symbol, exchange)
        segments = self.stock_business_segments(symbol, normalized, limit=limit)
        return {
            **segments,
            "history_mode": True,
        }


def _default_source_root() -> Path:
    return Path(__file__).resolve().parents[2] / "third_party" / "akshare"


def _install_package_stub(name: str, path: Path) -> None:
    module = sys.modules.get(name)
    if module is not None and list(getattr(module, "__path__", [])) == [str(path)]:
        return

    stub = types.ModuleType(name)
    stub.__path__ = [str(path)]  # type: ignore[attr-defined]
    stub.__package__ = name
    stub.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    sys.modules[name] = stub


@contextmanager
def _akshare_network_env():
    """Run AkShare public-source requests without inheriting broken host proxies."""

    if os.environ.get("AKSHARE_TRUST_ENV_PROXY") == "1":
        yield
        return

    proxy_keys = [
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ]
    previous = {key: os.environ.get(key) for key in proxy_keys}
    try:
        for key in proxy_keys:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _normalize_board_type(board_type: str) -> str:
    normalized = board_type.strip().lower()
    if normalized in {"concept", "concepts", "gn", "概念"}:
        return "concept"
    if normalized in {"theme", "themes", "zt", "主题", "题材"}:
        return "theme"
    if normalized in {"region", "regions", "area", "diyu", "地域", "地区"}:
        return "region"
    if normalized in {"industry", "industries", "hy", "行业"}:
        return "industry"
    raise AkShareSourceError(f"Unsupported board type: {board_type}")


def _records(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    bounded_limit = min(max(limit, 1), 500)
    return [_normalize_record(row) for row in df.head(bounded_limit).to_dict(orient="records")]


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def _tail_records(df: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if df.empty:
        return []
    bounded_limit = min(max(limit, 1), 3000)
    return [_normalize_record(row) for row in df.tail(bounded_limit).to_dict(orient="records")]


def _filter_bars_by_date(df: pd.DataFrame, start_date: str | date | None, end_date: str | date | None) -> pd.DataFrame:
    if df.empty or (not start_date and not end_date):
        return df
    date_column = _first_existing_column(df, ("date", "day", "datetime", "时间", "日期"))
    if not date_column:
        return df
    result = df.copy()
    parsed = pd.to_datetime(result[date_column], errors="coerce")
    if start_date:
        start = pd.Timestamp(_date_key(start_date))
        result = result[parsed >= start]
        parsed = parsed.loc[result.index]
    if end_date:
        end = pd.Timestamp(_date_key(end_date)) + pd.Timedelta(days=1)
        result = result[parsed < end]
    return result


def _all_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return [_normalize_record(row) for row in df.to_dict(orient="records")]


def _normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items() if str(key) not in {"_", "-", "index"}}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def _stock_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_record(row)
    return _stock_values_to_api(normalized, include_raw=True)


def _compact_stock_row_to_api(row: Mapping[str, Any]) -> dict[str, Any]:
    return _stock_values_to_api(row, include_raw=False)


def _stock_values_to_api(
    normalized: Mapping[str, Any],
    *,
    include_raw: bool,
) -> dict[str, Any]:
    raw_symbol = str(normalized.get("代码") or normalized.get("code") or "")
    symbol = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, symbol)
    vts = vt_symbol(symbol, exchange)
    turnover = _tencent_amount_to_yuan(
        normalized.get("成交额") or normalized.get("turnover")
    )
    quote_main_net_inflow = _tencent_amount_to_yuan(normalized.get("zljlr"))
    quote_main_inflow = _tencent_amount_to_yuan(normalized.get("zllr"))
    quote_main_outflow = _tencent_amount_to_yuan(normalized.get("zllc"))
    quote_main_net_inflow_ratio = (
        round(float(quote_main_net_inflow) / float(turnover) * 100, 6)
        if quote_main_net_inflow is not None and turnover
        else None
    )
    item = {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": vts,
        **stock_board_payload(vts, exchange),
        "name": _json_value(normalized.get("名称") or normalized.get("name")),
        "last_price": _number(normalized.get("最新价") or normalized.get("zxj")),
        "change": _number(normalized.get("涨跌额") or normalized.get("zd")),
        "change_pct": _number(normalized.get("涨跌幅") or normalized.get("zdf")),
        "open_price": _number(normalized.get("今开")),
        "high_price": _number(normalized.get("最高")),
        "low_price": _number(normalized.get("最低")),
        "previous_close": _number(normalized.get("昨收")),
        "volume": _number(normalized.get("成交量") or normalized.get("volume")),
        "turnover": turnover,
        "market_cap": _tencent_yi_yuan_to_yuan(normalized.get("总市值") or normalized.get("zsz")),
        "float_market_cap": _tencent_yi_yuan_to_yuan(normalized.get("流通市值") or normalized.get("ltsz")),
        "pe": _number(normalized.get("市盈率-动态") or normalized.get("pe_ttm")),
        "pb": _number(normalized.get("市净率")),
        "turnover_rate": _number(normalized.get("换手率") or normalized.get("hsl")),
        "volume_ratio": _number(normalized.get("量比") or normalized.get("lb")),
        "quote_speed": _number(normalized.get("涨速") or normalized.get("speed")),
        "quote_amplitude_pct": _number(
            normalized.get("振幅") or normalized.get("zf")
        ),
        "quote_main_net_inflow": quote_main_net_inflow,
        "quote_main_inflow": quote_main_inflow,
        "quote_main_outflow": quote_main_outflow,
        "quote_main_net_inflow_ratio": quote_main_net_inflow_ratio,
        "return_5d": _number(normalized.get("zdf_d5")),
        "return_10d": _number(normalized.get("zdf_d10")),
        "return_20d": _number(normalized.get("zdf_d20")),
        "source": "akshare.stock_zh_a_spot_tx",
    }
    if include_raw:
        item["raw"] = dict(normalized)
    return item


def _bar_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_record(row)
    trade_date = (
        normalized.get("日期")
        or normalized.get("时间")
        or normalized.get("day")
        or normalized.get("datetime")
        or normalized.get("date")
    )
    volume = _first_number(normalized, "成交量", "volume")
    explicit_turnover = _first_number(normalized, "成交额", "turnover", "turnover_yuan", "amount_yuan")
    if volume is None and "amount" in normalized and "成交额" not in normalized:
        volume = _number(normalized.get("amount"))
    return {
        "trade_date": trade_date,
        "open": _first_number(normalized, "开盘", "开盘价", "open"),
        "close": _first_number(normalized, "收盘", "收盘价", "close"),
        "high": _first_number(normalized, "最高", "最高价", "high"),
        "low": _first_number(normalized, "最低", "最低价", "low"),
        "volume": volume,
        "turnover": explicit_turnover,
        "turnover_rate": _first_number(normalized, "换手率", "turnover_rate", "turnoverratio", "hsl"),
        "change_pct": _first_number(normalized, "涨跌幅", "change_pct"),
    }


def _eastmoney_secucode(symbol: str, exchange: str) -> str:
    prefix = "SH" if exchange == "SSE" else "BJ" if exchange == "BSE" else "SZ"
    return f"{prefix}{symbol}"


def _format_tencent_trade_time(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) < 14:
        return text or None
    return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}:{text[12:14]}"


def _eastmoney_stock_kline(
    symbol: str,
    exchange: str,
    interval: str,
    limit: int,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> pd.DataFrame:
    period_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60", "1d": "101", "1w": "102", "1mo": "103"}
    period = period_map.get(interval)
    if period is None:
        raise AkShareSourceError(f"Unsupported EastMoney kline interval: {interval}")
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": period,
        "fqt": "0",
        "secid": eastmoney_secid(symbol, exchange),
        "beg": _date_key(start_date) if start_date else _history_start_for_limit(limit, interval),
        "end": _date_key(end_date) if end_date else "20500101",
    }
    response = None
    for host in ("https://push2his.eastmoney.com", "https://48.push2his.eastmoney.com", "https://push2delay.eastmoney.com"):
        try:
            with _akshare_network_env():
                response = requests.get(f"{host}/api/qt/stock/kline/get", params=params, timeout=8)
            response.raise_for_status()
            break
        except Exception:
            response = None
    if response is None:
        raise AkShareSourceError("EastMoney kline request failed")
    data = response.json().get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        return pd.DataFrame()
    rows = []
    for item in klines:
        parts = item.split(",")
        if len(parts) == 11:
            parts.append(None)
        if len(parts) < 12:
            continue
        rows.append(parts[:12])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows,
        columns=[
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "turnover",
            "amplitude",
            "change_pct",
            "change",
            "turnover_rate",
            "market_cap",
        ],
    )
    for column in ("open", "close", "high", "low", "volume", "turnover", "change_pct"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    parsed_dates = pd.to_datetime(df["date"], errors="coerce")
    df["date"] = parsed_dates if interval in {"1m", "5m", "15m", "30m", "60m"} else parsed_dates.dt.date
    df.dropna(subset=["date", "open", "close"], inplace=True)
    return df


def _eastmoney_board_kline(
    sector_id: str,
    board_type: str,
    limit: int,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> pd.DataFrame:
    normalized_type = _normalize_board_type(board_type)
    if normalized_type == "theme":
        normalized_type = "concept"
    if normalized_type not in {"concept", "industry"}:
        raise AkShareSourceError(f"Unsupported EastMoney board kline type: {board_type}")

    raw_sector_id = str(sector_id).strip()
    if _is_eastmoney_board_symbol(raw_sector_id):
        board_code = raw_sector_id.upper()
    else:
        board = _resolve_eastmoney_board(normalized_type, sector_id)
        board_code = str(board.get("id") or board.get("akshare_symbol") or sector_id).strip().upper()
    if not _is_eastmoney_board_symbol(board_code):
        raise AkShareSourceError(f"Unsupported EastMoney board symbol: {sector_id}")

    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "0",
        "secid": f"90.{board_code}",
        "beg": _date_key(start_date) if start_date else _history_start_for_limit(limit, "1d"),
        "end": _date_key(end_date) if end_date else "20500101",
    }
    for host in ("https://push2his.eastmoney.com", "https://48.push2his.eastmoney.com", "https://push2delay.eastmoney.com"):
        try:
            with _akshare_network_env():
                response = requests.get(f"{host}/api/qt/stock/kline/get", params=params, headers=EASTMONEY_HEADERS, timeout=8)
            response.raise_for_status()
            klines = (response.json().get("data") or {}).get("klines") or []
            frame = _eastmoney_kline_rows_to_frame(klines, interval="1d")
            if not frame.empty:
                return frame
        except Exception:
            continue
    raise AkShareSourceError("EastMoney board kline hosts returned no valid rows")


def _eastmoney_board_daily_quote(
    sector_id: str,
    *,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Return one completed official EastMoney board daily quote."""

    board_code = str(sector_id).strip().upper()
    if not _is_eastmoney_board_symbol(board_code):
        raise AkShareSourceError(
            f"Unsupported EastMoney board quote symbol: {sector_id}"
        )
    params = {
        "secid": f"90.{board_code}",
        "fields": (
            "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f86,f170"
        ),
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
    }
    payload: dict[str, Any] | None = None
    for host in (
        "https://push2delay.eastmoney.com",
        "http://push2delay.eastmoney.com",
    ):
        try:
            with _akshare_network_env():
                response = requests.get(
                    f"{host}/api/qt/stock/get",
                    params=params,
                    headers=EASTMONEY_HEADERS,
                    timeout=8,
                )
            response.raise_for_status()
            candidate = response.json().get("data")
            if isinstance(candidate, dict) and candidate:
                payload = candidate
                break
        except Exception:
            continue
    if payload is None:
        raise AkShareSourceError("EastMoney board daily quote request failed")
    return _eastmoney_board_daily_quote_frame(
        board_code,
        payload,
        now=now,
    )


def _eastmoney_board_daily_quote_frame(
    board_code: str,
    payload: Mapping[str, Any],
    *,
    now: datetime | None,
) -> pd.DataFrame:
    returned_code = str(payload.get("f57") or "").strip().upper()
    if returned_code != board_code:
        raise AkShareSourceError(
            f"EastMoney board daily quote code mismatch: {returned_code}"
        )
    try:
        source_timestamp = datetime.fromtimestamp(
            int(payload["f86"]),
            tz=SHANGHAI,
        )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise AkShareSourceError(
            "EastMoney board daily quote timestamp is invalid"
        ) from exc
    if int(payload.get("f86") or 0) <= 0:
        raise AkShareSourceError(
            "EastMoney board daily quote timestamp is invalid"
        )
    observed_at = now or datetime.now(SHANGHAI)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=SHANGHAI)
    else:
        observed_at = observed_at.astimezone(SHANGHAI)
    if source_timestamp.date() > observed_at.date():
        raise AkShareSourceError(
            "EastMoney board daily quote timestamp is in the future"
        )
    if (
        source_timestamp.date() == observed_at.date()
        and (source_timestamp.hour, source_timestamp.minute) < (15, 0)
    ):
        raise AkShareSourceError(
            "EastMoney board daily quote is incomplete"
        )

    decimal_places = _required_integer(payload, "f59", "decimal places")
    if not 0 <= decimal_places <= 8:
        raise AkShareSourceError(
            "EastMoney board daily quote decimal places are invalid"
        )
    divisor = float(10**decimal_places)
    prices = {
        "close": _required_number(payload, "f43", "close") / divisor,
        "high": _required_number(payload, "f44", "high") / divisor,
        "low": _required_number(payload, "f45", "low") / divisor,
        "open": _required_number(payload, "f46", "open") / divisor,
        "previous_close": (
            _required_number(payload, "f60", "previous close") / divisor
        ),
    }
    if any(value <= 0 for value in prices.values()):
        raise AkShareSourceError(
            "EastMoney board daily quote OHLC values must be positive"
        )
    if not (
        prices["low"]
        <= min(prices["open"], prices["close"])
        <= max(prices["open"], prices["close"])
        <= prices["high"]
    ):
        raise AkShareSourceError(
            "EastMoney board daily quote OHLC values are incoherent"
        )
    volume = _required_number(payload, "f47", "volume")
    turnover = _required_number(payload, "f48", "turnover")
    if volume < 0 or turnover < 0:
        raise AkShareSourceError(
            "EastMoney board daily quote volume is invalid"
        )
    change_pct = _required_number(payload, "f170", "change percent") / 100.0
    return pd.DataFrame.from_records(
        [
            {
                "date": source_timestamp.date(),
                "open": prices["open"],
                "close": prices["close"],
                "high": prices["high"],
                "low": prices["low"],
                "volume": volume,
                "turnover": turnover,
                "change_pct": change_pct,
                "previous_close": prices["previous_close"],
                "source_detail": "eastmoney.board_quote_daily",
                "source_timestamp": source_timestamp.isoformat(),
            }
        ]
    )


def _required_number(
    payload: Mapping[str, Any],
    field: str,
    label: str,
) -> float:
    value = _number(payload.get(field))
    if value is None or not math.isfinite(value):
        raise AkShareSourceError(
            f"EastMoney board daily quote {label} is invalid"
        )
    return float(value)


def _required_integer(
    payload: Mapping[str, Any],
    field: str,
    label: str,
) -> int:
    value = _required_number(payload, field, label)
    if not value.is_integer():
        raise AkShareSourceError(
            f"EastMoney board daily quote {label} is invalid"
        )
    return int(value)


def _sector_bar_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    item = _bar_row_to_api(row)
    source_detail = row.get("source_detail")
    if source_detail:
        item["raw"] = {
            "source_detail": str(source_detail),
            "source_timestamp": row.get("source_timestamp"),
            "previous_close": _number(row.get("previous_close")),
        }
    return item


def _eastmoney_kline_rows_to_frame(klines: Sequence[str], interval: str = "1d") -> pd.DataFrame:
    rows = []
    for item in klines:
        parts = str(item).split(",")
        if len(parts) == 11:
            parts.append(None)
        if len(parts) < 12:
            continue
        rows.append(parts[:12])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows,
        columns=[
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "turnover",
            "amplitude",
            "change_pct",
            "change",
            "turnover_rate",
            "market_cap",
        ],
    )
    for column in ("open", "close", "high", "low", "volume", "turnover", "change_pct"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    parsed_dates = pd.to_datetime(df["date"], errors="coerce")
    df["date"] = parsed_dates if interval in {"1m", "5m", "15m", "30m", "60m"} else parsed_dates.dt.date
    df.dropna(subset=["date", "open", "close"], inplace=True)
    return df


def _tencent_stock_kline_full(symbol: str, exchange: str, interval: str, limit: int) -> pd.DataFrame:
    period_map = {"1d": "day", "1w": "week", "1mo": "month"}
    period = period_map.get(interval)
    if period is None:
        raise AkShareSourceError(f"Unsupported Tencent kline interval: {interval}")

    prefixed = _prefixed_symbol(symbol, exchange)
    count = min(max(limit, 5), 3000)
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    params = {
        "_var": "kline_data",
        "param": f"{prefixed},{period},,,{count},",
        "r": str(random.random()),
    }
    with _akshare_network_env():
        response = requests.get(url, params=params, timeout=8)
    response.raise_for_status()
    payload = _parse_tencent_jsonp(response.text)
    data = (((payload or {}).get("data") or {}).get(prefixed) or {})
    rows = data.get(period) or []
    if not rows:
        return pd.DataFrame()

    cleaned_rows = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 9:
            continue
        cleaned_rows.append(
            {
                "date": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
                "volume": row[5],
                "turnover_rate": row[7],
                "turnover": row[8],
            }
        )
    if not cleaned_rows:
        return pd.DataFrame()

    df = pd.DataFrame(cleaned_rows)
    for column in ("open", "close", "high", "low", "volume", "turnover", "turnover_rate"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["turnover"] = df["turnover"] * 10_000
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df.dropna(subset=["date", "open", "close"], inplace=True)
    return df


def _parse_tencent_jsonp(text: str) -> dict[str, Any]:
    content = text.strip()
    if content.startswith("{"):
        return json.loads(content)
    start = content.find("=")
    if start < 0:
        raise AkShareSourceError("Tencent kline response is not valid JSONP")
    return json.loads(content[start + 1 :].rstrip(";"))


def _tencent_stock_kline(symbol: str, exchange: str, interval: str, limit: int) -> pd.DataFrame:
    period_map = {"1d": "day", "1w": "week", "1mo": "month"}
    period = period_map.get(interval)
    if period is None:
        raise AkShareSourceError(f"Unsupported Tencent kline interval: {interval}")

    prefixed = _prefixed_symbol(symbol, exchange)
    count = min(max(limit, 5), 3000)
    url = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
    params = {"param": f"{prefixed},{period},,,{count}"}
    with _akshare_network_env():
        response = requests.get(url, params=params, timeout=8)
    response.raise_for_status()
    payload = response.json()
    data = (((payload or {}).get("data") or {}).get(prefixed) or {})
    rows = data.get(period) or data.get("qfqday") or data.get("day") or []
    if not rows:
        return pd.DataFrame()
    cleaned_rows = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        cleaned_rows.append(row[:6])
    if not cleaned_rows:
        return pd.DataFrame()
    df = pd.DataFrame(cleaned_rows, columns=["date", "open", "close", "high", "low", "volume"])
    for column in ("open", "close", "high", "low", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df.dropna(subset=["date", "open", "close"], inplace=True)
    return df


def _stock_zh_a_spot_tx_page(module: Any, offset: int, count: int, sort: str = "price") -> tuple[pd.DataFrame, int | None]:
    del module
    url = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
    params = {
        "_appver": "11.17.0",
        "board_code": "aStock",
        "sort_type": _tencent_stock_sort_type(sort),
        "direct": "down",
        "offset": str(max(offset, 0)),
        "count": str(min(max(count, 1), 200)),
    }
    response = requests.get(url, params=params, timeout=15)
    data = response.json().get("data") or {}
    return pd.DataFrame(data.get("rank_list") or []), data.get("total")


EASTMONEY_BOARD_SOURCE = "eastmoney.push2.board"
EASTMONEY_BOARD_LIST_HOSTS = (
    "https://push2delay.eastmoney.com",
    "https://48.push2delay.eastmoney.com",
    "https://79.push2.eastmoney.com",
    "https://17.push2.eastmoney.com",
)
EASTMONEY_BOARD_MEMBER_HOSTS = (
    "https://push2delay.eastmoney.com",
    "https://48.push2delay.eastmoney.com",
    "https://29.push2.eastmoney.com",
)
EASTMONEY_STOCK_FUND_FLOW_HOSTS = (
    "https://push2.eastmoney.com",
    "https://48.push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
)
EASTMONEY_SECTOR_FUND_FLOW_HOSTS = (
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
    "https://48.push2.eastmoney.com",
)
EASTMONEY_HSF10_HOSTS = (
    "https://emweb.securities.eastmoney.com",
    "https://emweb.eastmoney.com",
)
EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
}


def _eastmoney_board_items(board_type: str) -> list[dict[str, Any]]:
    normalized_type = _normalize_board_type(board_type)
    if normalized_type == "theme":
        normalized_type = "concept"
    if normalized_type not in {"concept", "industry"}:
        return []
    rows: list[dict[str, Any]] = []
    page_size = 100
    first = _eastmoney_clist_get(
        EASTMONEY_BOARD_LIST_HOSTS,
        _eastmoney_board_list_params(normalized_type, page=1, page_size=page_size),
        timeout=12,
    )
    first_data = first.get("data") or {}
    rows.extend(row for row in (first_data.get("diff") or []) if isinstance(row, dict))
    total = int(first_data.get("total") or len(rows))
    total_pages = min(math.ceil(total / page_size), 10)
    for page in range(2, total_pages + 1):
        try:
            time.sleep(0.2)
            data = _eastmoney_clist_get(
                EASTMONEY_BOARD_LIST_HOSTS,
                _eastmoney_board_list_params(normalized_type, page=page, page_size=page_size),
                timeout=12,
            )
        except Exception:
            break
        rows.extend(row for row in ((data.get("data") or {}).get("diff") or []) if isinstance(row, dict))

    items = [
        _eastmoney_board_row_to_api(row, normalized_type)
        for row in rows
        if isinstance(row, dict)
    ]
    return sorted(items, key=lambda item: (_number(item.get("change_pct")) is None, -(_number(item.get("change_pct")) or -999), str(item.get("name") or "")))


def _eastmoney_stock_main_fund_flow(limit: int = 500) -> pd.DataFrame:
    page_size = 100
    params = _eastmoney_stock_main_fund_flow_params(page=1, page_size=page_size)
    data = _eastmoney_clist_get(EASTMONEY_STOCK_FUND_FLOW_HOSTS, params, timeout=12)
    first_data = data.get("data") or {}
    rows = [row for row in (first_data.get("diff") or []) if isinstance(row, dict)]
    total = int(first_data.get("total") or len(rows))
    total_pages = min(math.ceil(total / page_size), math.ceil(max(limit, 1) / page_size), 12)
    for page in range(2, total_pages + 1):
        try:
            time.sleep(0.2)
            data = _eastmoney_clist_get(
                EASTMONEY_STOCK_FUND_FLOW_HOSTS,
                _eastmoney_stock_main_fund_flow_params(page=page, page_size=page_size),
                timeout=12,
            )
        except Exception:
            break
        rows.extend(row for row in ((data.get("data") or {}).get("diff") or []) if isinstance(row, dict))
        if len(rows) >= limit:
            break

    normalized = [_eastmoney_stock_main_fund_flow_row(row) for row in rows[:limit]]
    return pd.DataFrame(normalized)


def _eastmoney_stock_main_fund_flow_params(page: int, page_size: int) -> dict[str, Any]:
    return {
        "fid": "f184",
        "po": "1",
        "pz": min(max(page_size, 1), 500),
        "pn": max(page, 1),
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fields": "f2,f3,f12,f13,f14,f62,f184,f225,f165,f263,f109,f175,f264,f160,f100,f124,f265,f1",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fs": "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
    }


def _eastmoney_stock_main_fund_flow_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "代码": row.get("f12"),
        "名称": row.get("f14"),
        "最新价": row.get("f2"),
        "今日排行榜-主力净额": row.get("f62"),
        "今日排行榜-主力净占比": row.get("f184"),
        "今日排行榜-今日排名": row.get("f225"),
        "今日排行榜-今日涨跌": row.get("f3"),
        "5日排行榜-主力净占比": row.get("f165"),
        "5日排行榜-5日排名": row.get("f263"),
        "5日排行榜-5日涨跌": row.get("f109"),
        "10日排行榜-主力净占比": row.get("f175"),
        "10日排行榜-10日排名": row.get("f264"),
        "10日排行榜-10日涨跌": row.get("f160"),
        "所属板块": row.get("f100"),
        "更新时间": row.get("f124"),
        "板块代码": row.get("f265"),
        "raw": row,
    }


def _eastmoney_sector_fund_flow(board_type: str, period: str, limit: int = 500) -> pd.DataFrame:
    normalized_type = _normalize_board_type(board_type)
    if normalized_type == "theme":
        normalized_type = "concept"
    if normalized_type not in {"concept", "industry"}:
        raise AkShareSourceError(f"Unsupported EastMoney fund-flow board type: {board_type}")

    period_config = _eastmoney_sector_fund_flow_period_config(period)
    page_size = 100
    params = _eastmoney_sector_fund_flow_params(
        normalized_type,
        page=1,
        page_size=page_size,
        period_config=period_config,
    )
    data = _eastmoney_clist_get(EASTMONEY_SECTOR_FUND_FLOW_HOSTS, params, timeout=12)
    first_data = data.get("data") or {}
    rows = [row for row in (first_data.get("diff") or []) if isinstance(row, dict)]
    total = int(first_data.get("total") or len(rows))
    total_pages = min(math.ceil(total / page_size), math.ceil(max(limit, 1) / page_size), 10)
    for page in range(2, total_pages + 1):
        try:
            time.sleep(0.2)
            data = _eastmoney_clist_get(
                EASTMONEY_SECTOR_FUND_FLOW_HOSTS,
                _eastmoney_sector_fund_flow_params(
                    normalized_type,
                    page=page,
                    page_size=page_size,
                    period_config=period_config,
                ),
                timeout=12,
            )
        except Exception:
            break
        rows.extend(row for row in ((data.get("data") or {}).get("diff") or []) if isinstance(row, dict))
        if len(rows) >= limit:
            break

    normalized = [
        _eastmoney_sector_fund_flow_row(row, normalized_type, index + 1, period_config)
        for index, row in enumerate(rows[:limit])
    ]
    return pd.DataFrame(normalized)


def _eastmoney_sector_fund_flow_period_config(period: str) -> dict[str, str]:
    normalized = str(period or "今日").strip()
    if normalized in {"即时", "今日", "1日", "当日"}:
        return {
            "period": "今日",
            "stat": "1",
            "sort_field": "f62",
            "change_field": "f3",
            "main_field": "f62",
            "main_ratio_field": "f184",
            "super_field": "f66",
            "super_ratio_field": "f69",
            "large_field": "f72",
            "large_ratio_field": "f75",
            "medium_field": "f78",
            "medium_ratio_field": "f81",
            "small_field": "f84",
            "small_ratio_field": "f87",
            "leader_field": "f204",
            "leader_code_field": "f205",
        }
    if normalized in {"5日", "5日排行"}:
        return {
            "period": "5日",
            "stat": "5",
            "sort_field": "f164",
            "change_field": "f109",
            "main_field": "f164",
            "main_ratio_field": "f165",
            "super_field": "f166",
            "super_ratio_field": "f167",
            "large_field": "f168",
            "large_ratio_field": "f169",
            "medium_field": "f170",
            "medium_ratio_field": "f171",
            "small_field": "f172",
            "small_ratio_field": "f173",
            "leader_field": "f257",
            "leader_code_field": "f258",
        }
    if normalized in {"10日", "10日排行"}:
        return {
            "period": "10日",
            "stat": "10",
            "sort_field": "f174",
            "change_field": "f160",
            "main_field": "f174",
            "main_ratio_field": "f175",
            "super_field": "f176",
            "super_ratio_field": "f177",
            "large_field": "f178",
            "large_ratio_field": "f179",
            "medium_field": "f180",
            "medium_ratio_field": "f181",
            "small_field": "f182",
            "small_ratio_field": "f183",
            "leader_field": "f260",
            "leader_code_field": "f261",
        }
    raise AkShareSourceError(f"Unsupported EastMoney sector fund-flow period: {period}")


def _eastmoney_sector_fund_flow_params(
    board_type: str,
    *,
    page: int,
    page_size: int,
    period_config: dict[str, str],
) -> dict[str, Any]:
    sector_type_code = "3" if board_type == "concept" else "2"
    fields = ",".join(
        [
            "f12",
            "f14",
            "f2",
            period_config["change_field"],
            period_config["main_field"],
            period_config["main_ratio_field"],
            period_config["super_field"],
            period_config["super_ratio_field"],
            period_config["large_field"],
            period_config["large_ratio_field"],
            period_config["medium_field"],
            period_config["medium_ratio_field"],
            period_config["small_field"],
            period_config["small_ratio_field"],
            period_config["leader_field"],
            period_config["leader_code_field"],
            "f104",
            "f105",
            "f106",
            "f124",
        ]
    )
    return {
        "pn": max(page, 1),
        "pz": min(max(page_size, 1), 500),
        "po": 1,
        "np": 1,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": 2,
        "invt": 2,
        "fid0": period_config["sort_field"],
        "fid": period_config["sort_field"],
        "fs": f"m:90 t:{sector_type_code}",
        "stat": period_config["stat"],
        "fields": fields,
        "rt": "52975239",
        "_": int(time.time() * 1000),
    }


def _eastmoney_sector_fund_flow_row(
    row: dict[str, Any],
    board_type: str,
    rank: int,
    period_config: dict[str, str],
) -> dict[str, Any]:
    update_date = _eastmoney_timestamp_date(row.get("f124"))
    source_updated_at = _eastmoney_timestamp_datetime(row.get("f124"))
    period_label = period_config["period"]
    return {
        "id": row.get("f12"),
        "代码": row.get("f12"),
        "名称": row.get("f14"),
        f"{period_label}涨跌幅": row.get(period_config["change_field"]),
        f"{period_label}主力净流入-净额": row.get(period_config["main_field"]),
        f"{period_label}主力净流入-净占比": row.get(period_config["main_ratio_field"]),
        f"{period_label}超大单净流入-净额": row.get(period_config["super_field"]),
        f"{period_label}超大单净流入-净占比": row.get(period_config["super_ratio_field"]),
        f"{period_label}大单净流入-净额": row.get(period_config["large_field"]),
        f"{period_label}大单净流入-净占比": row.get(period_config["large_ratio_field"]),
        f"{period_label}中单净流入-净额": row.get(period_config["medium_field"]),
        f"{period_label}中单净流入-净占比": row.get(period_config["medium_ratio_field"]),
        f"{period_label}小单净流入-净额": row.get(period_config["small_field"]),
        f"{period_label}小单净流入-净占比": row.get(period_config["small_ratio_field"]),
        f"{period_label}主力净流入最大股": row.get(period_config["leader_field"]),
        f"{period_label}主力净流入最大股代码": row.get(period_config["leader_code_field"]),
        "上涨家数": row.get("f104"),
        "下跌家数": row.get("f105"),
        "平盘家数": row.get("f106"),
        "rank": rank,
        "period": period_label,
        "type": board_type,
        "trade_date": update_date,
        "source_updated_at": source_updated_at,
        "updated_timestamp": row.get("f124"),
        "source": "eastmoney.sector_fund_flow_rank",
        "raw": row,
    }


def _eastmoney_timestamp_date(value: Any) -> str | None:
    number = _int_value(value)
    if not number:
        return None
    try:
        return datetime.fromtimestamp(number, timezone(timedelta(hours=8))).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _eastmoney_timestamp_datetime(value: Any) -> str | None:
    number = _int_value(value)
    if not number:
        return None
    try:
        return datetime.fromtimestamp(number, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _eastmoney_stock_hot_rank_items(limit: int = 100) -> list[dict[str, Any]]:
    rank_rows = _eastmoney_stock_hot_rank_raw(limit)
    secids = [_eastmoney_hot_rank_secid(row) for row in rank_rows]
    quote_map: dict[str, dict[str, Any]] = {}
    try:
        quote_map = {
            str(item.get("symbol")): item
            for item in (_eastmoney_quote_row_to_api(row) for row in _eastmoney_batch_quotes(secids) if isinstance(row, dict))
            if item.get("symbol")
        }
    except Exception:
        quote_map = {}

    items: list[dict[str, Any]] = []
    for row in rank_rows[: min(max(limit, 1), 500)]:
        raw_symbol = str(row.get("sc") or "")
        clean = _clean_stock_symbol(raw_symbol)
        exchange = _exchange_from_prefixed_symbol(raw_symbol, clean)
        quote = quote_map.get(clean) or {}
        items.append(
            {
                "symbol": clean,
                "exchange": exchange,
                "vt_symbol": vt_symbol(clean, exchange),
                "name": quote.get("name"),
                "rank": _int_value(row.get("rk")),
                "rank_change": _number(row.get("rc")),
                "hot_score": None,
                "last_price": quote.get("last_price"),
                "change_pct": quote.get("change_pct"),
                "raw": {**row, "quote": quote},
            }
        )
    return items


def _eastmoney_stock_hot_rank_raw(limit: int = 100) -> list[dict[str, Any]]:
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": min(max(limit, 1), 100),
    }
    headers = {
        **EASTMONEY_HEADERS,
        "Referer": "https://guba.eastmoney.com/rank/",
        "Content-Type": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.post(url, json=payload, headers=headers, timeout=12)
            response.raise_for_status()
            data = response.json()
            rows = data.get("data") or []
            if not isinstance(rows, list):
                raise AkShareSourceError("EastMoney hot rank response has no rows")
            return [row for row in rows if isinstance(row, dict)]
        except Exception as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1) + random.uniform(0.05, 0.2))
        finally:
            try:
                session.close()
            except Exception:
                pass
    raise AkShareSourceError(f"stock hot rank unavailable: {last_error.__class__.__name__ if last_error else 'unknown'}")


def _eastmoney_hot_rank_secid(row: dict[str, Any]) -> str:
    raw_symbol = str(row.get("sc") or "")
    clean = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, clean)
    return eastmoney_secid(clean, exchange)


def _eastmoney_search_board_items(query: str, limit: int = 20) -> list[dict[str, Any]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []
    rows = _eastmoney_search_raw(normalized_query, limit=max(limit * 3, 20))
    items: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("Classify") or "") != "BK":
            continue
        code = str(row.get("Code") or "").strip()
        name = str(row.get("Name") or code).strip()
        if not code or not name:
            continue
        board_type = _eastmoney_board_type_from_search(name, code)
        items.append(
            {
                "id": code,
                "akshare_symbol": code,
                "name": name,
                "type": board_type,
                "category": "东方财富板块",
                "path": [_board_path_label(board_type), "东方财富板块"],
                "source": "eastmoney.searchapi.board",
                "stock_count": None,
                "change_pct": None,
                "market_cap": None,
                "rise_count": None,
                "fall_count": None,
                "leader_stock": None,
            }
        )
        if len(items) >= limit:
            break
    return _dedupe_board_items(items)


def _eastmoney_board_members(
    board_type: str,
    symbol: str,
    limit: int = 100,
    page: int = 1,
    sort: str = "changepercent",
) -> dict[str, Any]:
    normalized_type = _normalize_board_type(board_type)
    board = _resolve_eastmoney_board(normalized_type, symbol)
    page_size = min(max(limit, 1), 500)
    params = _eastmoney_board_member_params(board["id"], page=max(page, 1), page_size=page_size, sort=sort)
    data = _eastmoney_clist_get(EASTMONEY_BOARD_MEMBER_HOSTS, params, timeout=12)
    rows = ((data.get("data") or {}).get("diff") or [])
    items = [
        _eastmoney_board_member_row_to_api(row)
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "items": items,
        "total": (data.get("data") or {}).get("total"),
        "type": board.get("type") or normalized_type,
        "symbol": board["id"],
        "sector": board,
        "source": EASTMONEY_BOARD_SOURCE,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _eastmoney_board_list_params(board_type: str, page: int, page_size: int) -> dict[str, Any]:
    return {
        "pn": max(page, 1),
        "pz": min(max(page_size, 1), 600),
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:90 t:3 f:!50" if board_type == "concept" else "m:90 t:2 f:!50",
        "fields": "f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f136",
    }


def _eastmoney_board_member_params(board_code: str, page: int, page_size: int, sort: str) -> dict[str, Any]:
    return {
        "pn": max(page, 1),
        "pz": min(max(page_size, 1), 500),
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": _eastmoney_stock_sort_field(sort),
        "fs": f"b:{board_code} f:!50",
        "fields": _eastmoney_board_member_fields(),
    }


def _eastmoney_board_member_fields() -> str:
    return "f2,f3,f4,f5,f6,f8,f9,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23"


def _eastmoney_clist_session() -> requests.Session:
    session = getattr(_EASTMONEY_SESSION_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.trust_env = False
        _EASTMONEY_SESSION_LOCAL.session = session
    return session


def _eastmoney_clist_get(hosts: tuple[str, ...], params: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        for host in hosts:
            try:
                response = _eastmoney_clist_session().get(
                    f"{host}/api/qt/clist/get",
                    params=params,
                    headers=EASTMONEY_HEADERS,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get("rc") not in (0, None):
                    raise AkShareSourceError(f"EastMoney board returned rc={data.get('rc') if isinstance(data, dict) else None}")
                if (data.get("data") or {}).get("diff") is None:
                    raise AkShareSourceError("EastMoney board response has no diff rows")
                return data
            except Exception as exc:
                last_error = exc
        if attempt < 2:
            time.sleep(0.35 * (attempt + 1) + random.uniform(0.05, 0.25))
    raise AkShareSourceError(f"EastMoney board request failed: {last_error.__class__.__name__ if last_error else 'unknown'}")


def _eastmoney_board_row_to_api(row: dict[str, Any], board_type: str) -> dict[str, Any]:
    normalized = _normalize_record(row)
    code = str(normalized.get("f12") or "").strip()
    name = str(normalized.get("f14") or code).strip()
    return {
        "id": code,
        "akshare_symbol": code,
        "name": name,
        "type": board_type,
        "category": "东方财富概念板块" if board_type == "concept" else "东方财富行业板块",
        "path": [_board_path_label(board_type), "东方财富"],
        "stock_count": _eastmoney_board_stock_count(normalized),
        "change_pct": _number(normalized.get("f3")),
        "market_cap": _number(normalized.get("f20")),
        "turnover_rate": _number(normalized.get("f8")),
        "rise_count": _number(normalized.get("f104")),
        "fall_count": _number(normalized.get("f105")),
        "leader_stock": normalized.get("f128"),
        "leader_change_pct": _number(normalized.get("f136")),
        "raw": normalized,
        "source": EASTMONEY_BOARD_SOURCE,
    }


def _eastmoney_board_member_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    item = _eastmoney_quote_row_to_api(row)
    return {**item, "source": EASTMONEY_BOARD_SOURCE}


def _eastmoney_hsf10_stock_sectors(symbol: str, exchange: str) -> list[dict[str, Any]]:
    code = _eastmoney_secucode(symbol, exchange)
    last_error: Exception | None = None
    for host in EASTMONEY_HSF10_HOSTS:
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(
                f"{host}/PC_HSF10/CoreConception/PageAjax",
                params={"code": code},
                headers={
                    **EASTMONEY_HEADERS,
                    "Referer": f"{host}/PC_HSF10/CoreConception/Index?type=web&code={code}",
                },
                timeout=12,
            )
            response.raise_for_status()
            data = response.json()
            rows = data.get("ssbk") if isinstance(data, dict) else None
            if rows is None:
                raise AkShareSourceError("EastMoney HSF10 response has no stock-board rows")
            return _eastmoney_hsf10_sector_rows_to_api(rows)
        except Exception as exc:
            last_error = exc
        finally:
            session.close()
    raise AkShareSourceError(f"EastMoney HSF10 stock sectors failed: {last_error.__class__.__name__ if last_error else 'unknown'}")


def _eastmoney_hsf10_sector_rows_to_api(rows: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_record(row)
        name = str(normalized.get("BOARD_NAME") or "").strip()
        board_id = _eastmoney_hsf10_board_id(normalized.get("BOARD_CODE"))
        if not name or not board_id:
            continue
        board_type = _eastmoney_hsf10_board_type(normalized)
        items.append(
            {
                "id": board_id,
                "akshare_symbol": board_id,
                "name": name,
                "type": board_type,
                "category": "东方财富所属板块",
                "path": [_board_path_label(board_type), "东方财富HSF10"],
                "rank": _int_value(normalized.get("BOARD_RANK")),
                "confirmed": True,
                "confirmation": "eastmoney_hsf10_stock_board",
                "is_precise": _boolish(normalized.get("IS_PRECISE")),
                "matched_keywords": [name],
                "source": "eastmoney.hsf10.core_conception",
                "raw": normalized,
            }
        )
    return sorted(
        items,
        key=lambda item: (
            _sector_type_order(str(item.get("type") or "")),
            _int_value(item.get("rank")) or 9999,
            str(item.get("name") or ""),
        ),
    )


def _eastmoney_hsf10_board_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.startswith("BK"):
        return text
    if text.isdigit():
        return f"BK{int(text):04d}"
    return text


def _eastmoney_hsf10_board_type(row: dict[str, Any]) -> str:
    name = str(row.get("BOARD_NAME") or "").strip()
    rank = _int_value(row.get("BOARD_RANK"))
    precise = _boolish(row.get("IS_PRECISE"))
    if name.endswith("板块"):
        return "region"
    if precise is True or "概念" in name:
        return "concept"
    if rank is not None and rank <= 3:
        return "industry"
    return "theme"


def _boolish(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _int_value(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _sector_type_order(sector_type: str) -> int:
    return {"industry": 0, "concept": 1, "region": 2, "theme": 3}.get(sector_type, 9)


def _eastmoney_board_stock_count(row: dict[str, Any]) -> int | None:
    rise = _number(row.get("f104"))
    fall = _number(row.get("f105"))
    if isinstance(rise, (int, float)) and isinstance(fall, (int, float)):
        return int(rise + fall)
    return None


def _resolve_eastmoney_board(board_type: str, symbol: str) -> dict[str, Any]:
    raw = symbol.strip()
    if _is_eastmoney_board_symbol(raw):
        search = _eastmoney_search_board_items(raw, limit=10)
        for item in search:
            if item.get("id") == raw:
                return item
        return {
            "id": raw,
            "akshare_symbol": raw,
            "name": raw,
            "type": "concept" if board_type == "theme" else board_type,
            "category": "东方财富板块",
            "path": [_board_path_label(board_type), "东方财富"],
            "source": EASTMONEY_BOARD_SOURCE,
        }
    search = _eastmoney_search_board_items(raw, limit=20)
    normalized_raw = _normalize_match_text(raw)
    for item in search:
        if _normalize_match_text(item.get("name")) == normalized_raw:
            return item
    if search:
        return search[0]
    for item in _eastmoney_board_items(board_type):
        if raw in {str(item.get("id")), str(item.get("akshare_symbol")), str(item.get("name"))}:
            return item
        if normalized_raw == _normalize_match_text(item.get("name")):
            return item
    raise AkShareSourceError(f"No EastMoney board found for {board_type}:{symbol}")


def _is_eastmoney_board_symbol(symbol: str) -> bool:
    return bool(re.match(r"^BK\d{4,}$", symbol.strip(), flags=re.IGNORECASE))


def _eastmoney_board_type_from_search(name: str, code: str) -> str:
    del code
    text = _normalize_match_text(name)
    if text.endswith("概念") or "概念" in text:
        return "concept"
    return "industry"


def _board_path_label(board_type: str) -> str:
    if board_type == "industry":
        return "行业"
    if board_type == "region":
        return "地域"
    if board_type == "theme":
        return "主题"
    return "概念"


def _dedupe_board_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        board_id = str(item.get("id") or "")
        if not board_id or board_id in seen:
            continue
        seen.add(board_id)
        result.append(item)
    return result


def _sina_all_a_page(page: int, page_size: int, sort: str) -> dict[str, Any]:
    with _akshare_network_env():
        total = _sina_sector_member_count("hs_a")
        rows = _sina_sector_member_rows("hs_a", page=page, page_size=page_size, sort=sort)
    return {
        "items": [_sina_all_a_row_to_api(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "source": "sina.market_center.hs_a",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _sina_all_a_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {**_sina_member_row_to_api(row), "source": "sina.market_center.hs_a"}


def _eastmoney_all_a_page(page: int, page_size: int, sort: str, order: str = "desc") -> dict[str, Any]:
    data = _eastmoney_clist_page(page=page, page_size=page_size, sort=sort, order=order)
    rows = (data.get("data") or {}).get("diff") or []
    return {
        "items": [_eastmoney_quote_row_to_api(row) for row in rows if isinstance(row, dict)],
        "page": page,
        "page_size": page_size,
        "total": (data.get("data") or {}).get("total"),
        "source": "eastmoney.push2delay.clist",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _eastmoney_clist_page(page: int, page_size: int, sort: str, order: str = "desc") -> dict[str, Any]:
    url = "https://48.push2delay.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": max(page, 1),
        "pz": min(max(page_size, 1), 200),
        "po": 1 if order.strip().lower() != "asc" else 0,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": _eastmoney_stock_sort_field(sort),
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": _eastmoney_quote_fields(),
    }
    with _akshare_network_env():
        response = requests.get(url, params=params, timeout=8)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("rc") not in (0, None):
        raise AkShareSourceError(f"EastMoney clist returned rc={data.get('rc') if isinstance(data, dict) else None}")
    return data


def _eastmoney_search_stock_quotes(query: str, limit: int) -> list[dict[str, Any]]:
    rows = _eastmoney_search_stocks(query, limit)
    secids = [
        str(row.get("QuoteID") or _eastmoney_quote_id_from_search(row))
        for row in rows
        if row.get("Classify") == "AStock" and (row.get("QuoteID") or _eastmoney_quote_id_from_search(row))
    ]
    secids = _dedupe_strings(secids)[:limit]
    if not secids:
        return []
    quotes = _eastmoney_batch_quotes(secids)
    quote_items = [_eastmoney_quote_row_to_api(row) for row in quotes if isinstance(row, dict)]
    if len(quote_items) >= len(secids):
        return quote_items[:limit]

    quote_map = {str(item.get("symbol")): item for item in quote_items}
    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("Classify") != "AStock":
            continue
        code = str(row.get("Code") or row.get("UnifiedCode") or "").strip()
        item = quote_map.get(code)
        if item:
            result.append(item)
        else:
            exchange = _eastmoney_exchange_from_market(row.get("MktNum") or row.get("JYS"), code)
            result.append(
                {
                    "symbol": code,
                    "exchange": exchange,
                    "vt_symbol": vt_symbol(code, exchange),
                    "name": row.get("Name") or code,
                    "last_price": None,
                    "change": None,
                    "change_pct": None,
                    "open_price": None,
                    "high_price": None,
                    "low_price": None,
                    "previous_close": None,
                    "volume": None,
                    "turnover": None,
                    "market_cap": None,
                    "float_market_cap": None,
                    "pe": None,
                    "pb": None,
                    "turnover_rate": None,
                    "volume_ratio": None,
                    "raw": row,
                    "source": "eastmoney.searchapi",
                }
            )
        if len(result) >= limit:
            break
    return result


def _eastmoney_search_stocks(query: str, limit: int) -> list[dict[str, Any]]:
    rows = _eastmoney_search_raw(query, limit)
    return [row for row in rows if isinstance(row, dict) and row.get("Classify") == "AStock"]


def _eastmoney_search_raw(query: str, limit: int) -> list[dict[str, Any]]:
    url = "https://searchapi.eastmoney.com/api/suggest/get"
    params = {
        "input": query.strip(),
        "type": 14,
        "token": "D43BF722C8E33BD8A1FAE0C7B72A8E36",
        "count": min(max(limit * 3, 10), 100),
    }
    with _akshare_network_env():
        response = requests.get(url, params=params, timeout=8)
    response.raise_for_status()
    data = response.json()
    rows = (((data or {}).get("QuotationCodeTable") or {}).get("Data") or [])
    return [row for row in rows if isinstance(row, dict)]


def _eastmoney_batch_quotes(secids: list[str]) -> list[dict[str, Any]]:
    if not secids:
        return []
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "secids": ",".join(secids[:100]),
        "fields": _eastmoney_quote_fields(),
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
    }
    try:
        with _akshare_network_env():
            response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
    except Exception:
        url = "https://48.push2delay.eastmoney.com/api/qt/ulist.np/get"
        with _akshare_network_env():
            response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
    data = response.json()
    rows = ((data or {}).get("data") or {}).get("diff") or []
    return [row for row in rows if isinstance(row, dict)]


def _eastmoney_index_quotes() -> list[Quote]:
    secids = [
        eastmoney_secid(item["symbol"], item.get("exchange"))
        for item in INDEX_SYMBOLS
    ]
    rows = _eastmoney_batch_quotes(secids)
    quote_by_key = {
        f"{item.get('symbol')}.{item.get('exchange')}": item
        for item in (_eastmoney_quote_row_to_api(row) for row in rows if isinstance(row, dict))
    }
    quotes: list[Quote] = []
    for index_def in INDEX_SYMBOLS:
        exchange = normalize_exchange(index_def["symbol"], index_def.get("exchange"))
        item = quote_by_key.get(f"{index_def['symbol']}.{exchange}")
        if not item:
            continue
        item = {**item, "name": index_def.get("name") or item.get("name"), "source": "eastmoney.push2.index"}
        quotes.append(_quote_from_api(item))
    return quotes


def _sina_index_quotes() -> list[Quote]:
    module = importlib.import_module("akshare.index.index_stock_zh")
    with _akshare_network_env():
        df = module.stock_zh_index_spot_sina()
    rows = {_clean_index_symbol(row.get("代码")): row for row in _all_records(df)}
    quotes: list[Quote] = []
    for item in INDEX_SYMBOLS:
        code = _prefixed_symbol(item["symbol"], item.get("exchange"))
        row = rows.get(code)
        if row:
            quotes.append(_quote_from_api(_index_row_to_api(row, item)))
    return quotes


def _eastmoney_quote_fields() -> str:
    return "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f22,f23,f62,f109,f110,f124,f160,f184"


def _eastmoney_stock_page_is_fresh(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    current_at = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    minute = current_at.hour * 60 + current_at.minute
    if not (9 * 60 + 15 <= minute <= 11 * 60 + 30 or 13 * 60 <= minute <= 15 * 60):
        return True

    items = [row for row in payload.get("items") or [] if isinstance(row, Mapping)]
    if not items:
        return False
    fresh_count = 0
    for row in items:
        raw_time = row.get("quote_observed_at")
        try:
            observed_at = datetime.fromisoformat(str(raw_time))
        except (TypeError, ValueError):
            continue
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            continue
        age_seconds = (current_at - observed_at.astimezone(SHANGHAI)).total_seconds()
        if -5.0 <= age_seconds <= EASTMONEY_LIVE_PAGE_MAX_AGE_SECONDS:
            fresh_count += 1
    return fresh_count / len(items) >= EASTMONEY_LIVE_PAGE_MIN_FRESH_RATIO


def _eastmoney_stock_sort_field(sort: str) -> str:
    normalized = sort.strip().lower()
    sort_map = {
        "price": "f2",
        "last_price": "f2",
        "change_pct": "f3",
        "changepercent": "f3",
        "return": "f3",
        "turnover": "f6",
        "amount": "f6",
        "volume": "f5",
        "turnover_rate": "f8",
        "turnoverratio": "f8",
        "hsl": "f8",
        "pe": "f9",
        "pb": "f23",
        "market_cap": "f20",
        "mktcap": "f20",
        "zsz": "f20",
        "float_market_cap": "f21",
        "nmc": "f21",
        "return_5d": "f109",
        "return_10d": "f160",
        "return_20d": "f110",
        "volume_ratio": "f10",
        "volumeratio": "f10",
    }
    return sort_map.get(normalized, "f20")


def _eastmoney_quote_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_record(row)
    symbol = str(normalized.get("f12") or "").strip()
    exchange = _eastmoney_exchange_from_market(normalized.get("f13"), symbol)
    vts = vt_symbol(symbol, exchange)
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": vts,
        **stock_board_payload(vts, exchange),
        "name": normalized.get("f14") or symbol,
        "last_price": _number(normalized.get("f2")),
        "quote_observed_at": _eastmoney_timestamp_datetime(
            normalized.get("f124")
        ),
        "change": _number(normalized.get("f4")),
        "change_pct": _number(normalized.get("f3")),
        "open_price": _number(normalized.get("f17")),
        "high_price": _number(normalized.get("f15")),
        "low_price": _number(normalized.get("f16")),
        "previous_close": _number(normalized.get("f18")),
        "volume": _number(normalized.get("f5")),
        "turnover": _number(normalized.get("f6")),
        "market_cap": _number(normalized.get("f20")),
        "float_market_cap": _number(normalized.get("f21")),
        "pe": _number(normalized.get("f9")),
        "pb": _number(normalized.get("f23")),
        "turnover_rate": _number(normalized.get("f8")),
        "volume_ratio": _number(normalized.get("f10")),
        "quote_speed": _number(normalized.get("f22")),
        "quote_amplitude_pct": _number(normalized.get("f7")),
        "quote_main_net_inflow": _number(normalized.get("f62")),
        "quote_main_net_inflow_ratio": _number(normalized.get("f184")),
        "return_5d": _number(normalized.get("f109")),
        "return_10d": _number(normalized.get("f160")),
        "return_20d": _number(normalized.get("f110")),
        "raw": normalized,
        "source": "eastmoney.push2",
    }


def _eastmoney_quote_id_from_search(row: dict[str, Any]) -> str | None:
    code = str(row.get("Code") or row.get("UnifiedCode") or "").strip()
    if not code:
        return None
    market = _eastmoney_market_id_from_search(row.get("MktNum") or row.get("JYS"), code)
    return f"{market}.{code}"


def _eastmoney_exchange_from_market(value: Any, symbol: str) -> str:
    text = str(value or "").strip().upper()
    inferred = normalize_exchange(symbol)
    if inferred == "BSE":
        return "BSE"
    if text in {"1", "SH", "SHSE", "SSE"}:
        return "SSE"
    if text in {"0", "SZ", "SZSE"}:
        return "SZSE"
    if text in {"2", "BJ", "BSE", "81"}:
        return "BSE"
    return inferred


def _eastmoney_market_id_from_search(value: Any, symbol: str) -> str:
    exchange = _eastmoney_exchange_from_market(value, symbol)
    return "1" if exchange == "SSE" else "0"


def _index_row_to_api(row: dict[str, Any], index_def: dict[str, str]) -> dict[str, Any]:
    symbol = index_def["symbol"]
    exchange = normalize_exchange(symbol, index_def.get("exchange"))
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": vt_symbol(symbol, exchange),
        "name": row.get("名称") or index_def.get("name") or symbol,
        "last_price": _number(row.get("最新价")),
        "change": _number(row.get("涨跌额")),
        "change_pct": _number(row.get("涨跌幅")),
        "open_price": _number(row.get("今开")),
        "high_price": _number(row.get("最高")),
        "low_price": _number(row.get("最低")),
        "previous_close": _number(row.get("昨收")),
        "volume": _number(row.get("成交量")),
        "turnover": _number(row.get("成交额")),
        "market_cap": None,
        "pe": None,
        "pb": None,
        "turnover_rate": None,
        "industry": None,
        "area": None,
        "trade_time": None,
        "source": "akshare.stock_zh_index_spot_sina",
    }


def _clean_index_symbol(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "." in text:
        suffix, code = text.split(".", 1)
        if suffix in {"sh", "sz", "bj"}:
            return f"{suffix}{code}"
    return text


def _quote_from_api(data: dict[str, Any]) -> Quote:
    return Quote(
        symbol=str(data.get("symbol") or ""),
        exchange=str(data.get("exchange") or normalize_exchange(str(data.get("symbol") or ""))),
        vt_symbol=str(data.get("vt_symbol") or vt_symbol(str(data.get("symbol") or ""), data.get("exchange"))),
        name=str(data.get("name") or data.get("symbol") or ""),
        last_price=_number(data.get("last_price")),
        change=_number(data.get("change")),
        change_pct=_number(data.get("change_pct")),
        open_price=_number(data.get("open_price")),
        high_price=_number(data.get("high_price")),
        low_price=_number(data.get("low_price")),
        previous_close=_number(data.get("previous_close")),
        volume=_number(data.get("volume")),
        turnover=_number(data.get("turnover")),
        market_cap=_number(data.get("market_cap")),
        pe=_number(data.get("pe")),
        pb=_number(data.get("pb")),
        turnover_rate=_number(data.get("turnover_rate")),
        industry=data.get("industry"),
        area=data.get("area"),
        trade_time=data.get("trade_time"),
        source=str(data.get("source") or "akshare"),
    )


def _business_segment_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("主营构成"),
        "type": row.get("分类类型"),
        "revenue": _number(row.get("主营收入")),
        "revenue_ratio": _ratio_to_percent(row.get("收入比例")),
        "cost": _number(row.get("主营成本")),
        "cost_ratio": _ratio_to_percent(row.get("成本比例")),
        "gross_profit": _number(row.get("主营利润")),
        "gross_profit_ratio": _ratio_to_percent(row.get("毛利率")),
        "profit_ratio": _ratio_to_percent(row.get("利润比例")),
        "rank": None,
        "report_date": row.get("报告日期"),
        "source": "akshare.stock_zygc_em",
    }


def _ratio_to_percent(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number * 100 if abs(number) <= 1 else number


def _tencent_amount_to_yuan(value: Any) -> float | int | None:
    number = _number(value)
    return round(number * 10_000, 2) if number is not None else None


def _tencent_yi_yuan_to_yuan(value: Any) -> float | int | None:
    number = _number(value)
    return round(number * 100_000_000, 2) if number is not None else None


def _sina_wan_yuan_to_yuan(value: Any) -> float | int | None:
    number = _number(value)
    return round(number * 10_000, 2) if number is not None else None


def _latest_value(values: list[Any]) -> Any:
    cleaned = [value for value in values if value not in (None, "")]
    return max(cleaned) if cleaned else None


def _prefixed_symbol(symbol: str, exchange: str) -> str:
    if exchange == "SSE":
        return f"sh{symbol}"
    if exchange == "BSE":
        return f"bj{symbol}"
    return f"sz{symbol}"


def _history_start_for_limit(limit: int, interval: str) -> str:
    multiplier = 3 if interval == "1w" else 6 if interval == "1mo" else 2
    days = max(limit * multiplier, 260)
    return (date.today() - timedelta(days=days)).strftime("%Y%m%d")


def _date_key(value: str | date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return ""
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return text


def _is_index_symbol(symbol: str, exchange: str) -> bool:
    return any(item["symbol"] == symbol and normalize_exchange(symbol, item.get("exchange")) == exchange for item in INDEX_SYMBOLS)


def _index_name(symbol: str) -> str:
    for item in INDEX_SYMBOLS:
        if item["symbol"] == symbol:
            return item["name"]
    return symbol


def _normalize_interval(interval: str) -> str:
    normalized = interval.lower().strip()
    aliases = {
        "day": "1d",
        "daily": "1d",
        "d": "1d",
        "week": "1w",
        "weekly": "1w",
        "w": "1w",
        "month": "1mo",
        "monthly": "1mo",
        "m": "1mo",
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "60min": "60m",
    }
    return aliases.get(normalized, normalized)


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    temp = df.copy()
    date_col = "date" if "date" in temp.columns else "日期"
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp.dropna(subset=[date_col], inplace=True)
    temp.set_index(date_col, inplace=True)
    aggregations = {
        "open": "first",
        "close": "last",
        "high": "max",
        "low": "min",
    }
    if "volume" in temp.columns:
        aggregations["volume"] = "sum"
    if "turnover" in temp.columns:
        aggregations["turnover"] = "sum"
    if "amount" in temp.columns:
        aggregations["amount"] = "sum"
    result = temp.resample(rule).agg(aggregations)
    result.dropna(subset=["open", "close"], inplace=True)
    result.reset_index(inplace=True)
    result.rename(columns={date_col: "date"}, inplace=True)
    return result


def _parse_akshare_sector_id(sector_id: str) -> tuple[str, str]:
    if sector_id.startswith("ak_concept_"):
        return "concept", sector_id.removeprefix("ak_concept_")
    if sector_id.startswith("ak_industry_"):
        return "industry", sector_id.removeprefix("ak_industry_")
    if sector_id.startswith("ak_region_"):
        return "region", sector_id.removeprefix("ak_region_")
    if sector_id.startswith("ak_theme_"):
        return "theme", sector_id.removeprefix("ak_theme_")
    if sector_id.startswith(("chgn_", "gn_")):
        return "concept", sector_id
    if sector_id.startswith(("sw_", "sw1_", "sw2_", "sw3_", "new_")):
        return "industry", sector_id
    if sector_id.startswith("diyu_"):
        return "region", sector_id
    if sector_id.startswith("BK"):
        return "concept", sector_id
    return "industry", sector_id


def _normalize_sector_query_type(sector_type: str) -> str:
    normalized = sector_type.strip().lower()
    if normalized in {"", "industry", "hy", "行业"}:
        return "industry" if normalized else ""
    if normalized in {"concept", "theme", "gn", "概念", "主题"}:
        return "concept" if normalized != "theme" else "theme"
    if normalized in {"region", "area", "diyu", "地域", "地区"}:
        return "region"
    return normalized


@lru_cache(maxsize=1)
def _sina_classify_boards() -> dict[str, pd.DataFrame]:
    module = importlib.import_module("akshare.stock_feature.stock_classify_sina")
    with _akshare_network_env():
        return module.stock_classify_board()


def _sina_sector_items(board_type: str) -> list[dict[str, Any]]:
    normalized_type = _normalize_board_type(board_type)
    boards = _sina_classify_boards()
    category_names = _sina_category_names(normalized_type)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in category_names:
        df = boards.get(category)
        if df is None or df.empty:
            continue
        for row in _all_records(df):
            raw_code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if not raw_code or not name:
                continue
            item_type = _sina_sector_type(raw_code, category, normalized_type)
            sector_id = raw_code
            if sector_id in seen:
                continue
            seen.add(sector_id)
            items.append(
                {
                    "id": sector_id,
                    "akshare_symbol": raw_code,
                    "name": name,
                    "type": item_type,
                    "category": category,
                    "path": _sina_sector_path(category, item_type),
                    "stock_count": None,
                    "source": "akshare.stock_classify_sina",
                }
            )
    return sorted(items, key=lambda item: (str(item.get("type") or ""), str(item.get("category") or ""), str(item.get("name") or "")))


def _sina_category_names(board_type: str) -> tuple[str, ...]:
    if board_type == "concept":
        return ("热门概念",)
    if board_type == "theme":
        return ("热门概念",)
    if board_type == "region":
        return ("地域板块",)
    return ("申万行业", "申万一级", "申万二级", "申万三级", "新浪行业")


def _sina_sector_type(code: str, category: str, requested_type: str) -> str:
    if category == "地域板块" or code.startswith("diyu_"):
        return "region"
    if category == "热门概念" or code.startswith(("chgn_", "gn_")):
        return "concept" if requested_type != "theme" else "theme"
    return "industry"


def _sina_sector_path(category: str, sector_type: str) -> list[str]:
    label = {"industry": "行业", "concept": "概念", "theme": "主题", "region": "地域"}.get(sector_type, sector_type)
    return [label, category] if category != label else [label]


def _resolve_sina_sector(board_type: str, symbol: str) -> dict[str, Any]:
    normalized_type = _normalize_board_type(board_type)
    raw_symbol = symbol.strip()
    raw_without_prefix = (
        raw_symbol.removeprefix("ak_concept_")
        .removeprefix("ak_industry_")
        .removeprefix("ak_region_")
        .removeprefix("ak_theme_")
    )
    candidates: list[dict[str, Any]] = []
    for item in _sina_sector_items(normalized_type):
        if raw_symbol in {str(item.get("id")), str(item.get("akshare_symbol")), str(item.get("name"))}:
            return item
        if raw_without_prefix in {str(item.get("id")), str(item.get("akshare_symbol")), str(item.get("name"))}:
            return item
        if _normalize_match_text(raw_symbol) == _normalize_match_text(item.get("name")):
            candidates.append(item)
    if candidates:
        return candidates[0]
    raise AkShareSourceError(f"No AkShare/Sina sector found for {board_type}:{symbol}")


def _sina_sector_member_count(node: str) -> int | None:
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
    response = requests.get(url, params={"node": node}, timeout=15)
    try:
        return int(response.json())
    except Exception:
        text = response.text.strip()
        return int(text) if text.isdigit() else None


def _sina_sector_member_rows(node: str, page: int, page_size: int, sort: str) -> list[dict[str, Any]]:
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": max(page, 1),
        "num": min(max(page_size, 1), 500),
        "sort": _sina_member_sort(sort),
        "asc": 0,
        "node": node,
        "symbol": "",
        "_s_r_a": "init",
    }
    response = requests.get(
        url,
        params=params,
        timeout=FULL_MARKET_OHLCV_SPOT_REQUEST_TIMEOUT_SECONDS,
    )
    data = response.json()
    if not isinstance(data, list):
        raise AkShareSourceError(f"Sina sector node returned {type(data).__name__}")
    return [_normalize_record(row) for row in data if isinstance(row, dict)]


def _sina_member_sort(sort: str) -> str:
    normalized = sort.strip().lower()
    sort_map = {
        "change_pct": "changepercent",
        "changepercent": "changepercent",
        "return": "changepercent",
        "amount": "amount",
        "turnover": "amount",
        "volume": "volume",
        "market_cap": "mktcap",
        "mktcap": "mktcap",
        "turnover_rate": "turnoverratio",
        "turnoverratio": "turnoverratio",
        "price": "trade",
        "last_price": "trade",
        "symbol": "symbol",
        "code": "symbol",
    }
    return sort_map.get(normalized, "changepercent")


def _sina_member_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_record(row)
    raw_symbol = str(normalized.get("code") or normalized.get("symbol") or "")
    symbol = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, symbol)
    prefixed_symbol = str(normalized.get("symbol") or "")
    vts = vt_symbol(symbol, exchange)
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": vts,
        **stock_board_payload(vts, exchange),
        "name": normalized.get("name") or symbol,
        "last_price": _number(normalized.get("trade")),
        "change": _number(normalized.get("pricechange")),
        "change_pct": _number(normalized.get("changepercent")),
        "open_price": _number(normalized.get("open")),
        "high_price": _number(normalized.get("high")),
        "low_price": _number(normalized.get("low")),
        "previous_close": _number(normalized.get("settlement")),
        "volume": _number(normalized.get("volume")),
        "turnover": _number(normalized.get("amount")),
        "market_cap": _sina_wan_yuan_to_yuan(normalized.get("mktcap")),
        "float_market_cap": _sina_wan_yuan_to_yuan(normalized.get("nmc")),
        "pe": _number(normalized.get("per")),
        "pb": _number(normalized.get("pb")),
        "turnover_rate": _number(normalized.get("turnoverratio")),
        "volume_ratio": None,
        "return_5d": None,
        "return_10d": None,
        "return_20d": None,
        "trade_time": normalized.get("ticktime"),
        "raw_symbol": prefixed_symbol,
        "raw": normalized,
        "source": "akshare.stock_classify_sina",
    }


def _sina_full_market_ohlcv_page(page: int) -> list[dict[str, Any]]:
    """Read one full-market page with bounded retries for transient Sina errors."""

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            rows = _sina_sector_member_rows(
                "hs_a",
                page=page,
                page_size=FULL_MARKET_OHLCV_SPOT_PAGE_SIZE,
                sort="symbol",
            )
            if rows:
                return rows
            raise AkShareSourceError("Sina A-share page returned no rows")
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))

    detail = str(last_error).strip() if last_error else "unknown error"
    raise AkShareSourceError(
        f"Sina A-share page {page} unavailable: {detail[:200]}"
    ) from last_error


def _sina_ohlcv_spot_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields required to form a provisional intraday daily bar."""

    item = _sina_member_row_to_api(row)
    return {
        "symbol": item["symbol"],
        "exchange": item["exchange"],
        "vt_symbol": item["vt_symbol"],
        "name": item["name"],
        "last_price": item["last_price"],
        "open_price": item["open_price"],
        "high_price": item["high_price"],
        "low_price": item["low_price"],
        "volume": item["volume"],
        "turnover": item["turnover"],
        "turnover_rate": item["turnover_rate"],
        "trade_time": item["trade_time"],
        "source": "sina.market_center.hs_a_ohlcv",
    }


def _candidate_sectors_for_text(text: str) -> list[dict[str, Any]]:
    normalized_text = _normalize_match_text(text)
    if not normalized_text:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for board_type in ("industry", "concept", "region"):
        for item in _sina_sector_items(board_type):
            name = str(item.get("name") or "")
            normalized_name = _normalize_match_text(name)
            if not normalized_name:
                continue
            matched_terms = [name]
            score = 0
            if normalized_name in normalized_text:
                score += min(len(normalized_name), 20) + 20
            if score <= 0:
                continue
            if item.get("type") == "industry":
                score += 5
            scored.append((score, {**item, "matched_keywords": _dedupe_strings(matched_terms)}))
    scored.sort(key=lambda value: (-value[0], str(value[1].get("type") or ""), str(value[1].get("name") or "")))
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, item in scored:
        sector_id = str(item.get("id") or "")
        if sector_id in seen:
            continue
        seen.add(sector_id)
        result.append(item)
    return result


def _dedupe_sector_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        sector_id = str(item.get("id") or item.get("name") or "")
        key = f"{item.get('type')}:{sector_id}:{item.get('name')}"
        if not sector_id or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _normalize_match_text(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _split_terms(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value)
    separators = ("、", "，", ",", ";", "；", "/", " ")
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return _dedupe_strings([part.strip() for part in text.split(separators[0]) if part.strip()])


def _requires_local_stock_sort(sort: str) -> bool:
    return _tencent_stock_sort_type(sort) == "local"


def _tencent_stock_sort_type(sort: str) -> str:
    normalized = sort.strip().lower()
    sort_map = {
        "price": "price",
        "last_price": "price",
        "turnover": "turnover",
        "amount": "turnover",
        "volume": "volume",
        "change_pct": "local",
        "changepercent": "local",
        "return_5d": "local",
        "return_10d": "local",
        "return_20d": "local",
        "market_cap": "local",
        "mktcap": "local",
        "zsz": "local",
        "turnover_rate": "local",
        "turnoverratio": "local",
        "hsl": "local",
    }
    return sort_map.get(normalized, "price")


def _sort_stock_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    normalized = sort.strip().lower()
    key_map = {
        "change_pct": "zdf",
        "changepercent": "zdf",
        "return_5d": "zdf_d5",
        "return_10d": "zdf_d10",
        "return_20d": "zdf_d20",
        "market_cap": "zsz",
        "mktcap": "zsz",
        "turnover_rate": "hsl",
        "turnoverratio": "hsl",
    }
    key = key_map.get(normalized, "zsz")
    return sorted(rows, key=lambda row: _number(row.get(key)) or float("-inf"), reverse=True)


def _period_returns_from_bars(bars: list[dict[str, Any]], windows: tuple[int, ...]) -> dict[str, float | None]:
    closes = [_number(bar.get("close")) for bar in bars]
    valid = [value for value in closes if value is not None]
    result: dict[str, float | None] = {}
    for window in windows:
        key = f"return_{window}d"
        if len(valid) <= window:
            result[key] = None
            continue
        start = valid[-window - 1]
        end = valid[-1]
        result[key] = (end / start - 1) * 100 if start else None
    return result


def _ensure_return_keys(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "return_5d": item.get("return_5d"),
        "return_10d": item.get("return_10d"),
        "return_20d": item.get("return_20d"),
    }


def _sector_trend_from_items(sector_id: str, items: list[dict[str, Any]], source: str) -> dict[str, Any]:
    changes = [_number(item.get("change_pct")) for item in items]
    valid_changes = [value for value in changes if value is not None]
    rise_count = sum(1 for value in valid_changes if value > 0)
    flat_count = sum(1 for value in valid_changes if value == 0)
    fall_count = sum(1 for value in valid_changes if value < 0)
    sample_size = len(valid_changes)
    rise_ratio = rise_count / sample_size * 100 if sample_size else None
    fall_ratio = fall_count / sample_size * 100 if sample_size else None
    avg_change_pct = sum(valid_changes) / sample_size if sample_size else None
    ranked = sorted(
        [item for item in items if _number(item.get("change_pct")) is not None],
        key=lambda item: _number(item.get("change_pct")) or 0,
        reverse=True,
    )
    return {
        "sector_id": sector_id,
        "trend_state": _sector_trend_state(avg_change_pct, rise_ratio),
        "sample_size": sample_size,
        "rise_count": rise_count,
        "flat_count": flat_count,
        "fall_count": fall_count,
        "rise_ratio": rise_ratio,
        "fall_ratio": fall_ratio,
        "avg_change_pct": avg_change_pct,
        "turnover_weighted_change_pct": _weighted_change(items, "turnover"),
        "market_cap_weighted_change_pct": _weighted_change(items, "market_cap"),
        "turnover": sum(_number(item.get("turnover")) or 0 for item in items),
        "limit_up_count": sum(1 for value in valid_changes if value >= 9.8),
        "limit_down_count": sum(1 for value in valid_changes if value <= -9.8),
        "top_gainers": ranked[:5],
        "top_losers": list(reversed(ranked[-5:])),
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _weighted_change(items: list[dict[str, Any]], weight_key: str) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for item in items:
        change = _number(item.get("change_pct"))
        weight = _number(item.get(weight_key))
        if change is None or weight is None or weight <= 0:
            continue
        numerator += change * weight
        denominator += weight
    return numerator / denominator if denominator else None


def _sector_trend_state(change_pct: float | None, rise_ratio: float | None) -> str:
    if change_pct is None:
        return "UNKNOWN"
    if change_pct >= 1.0 and (rise_ratio is None or rise_ratio >= 55):
        return "UP"
    if change_pct <= -1.0 and (rise_ratio is None or rise_ratio <= 45):
        return "DOWN"
    return "RANGE"


def _infer_market_state(indices: list[dict[str, Any]]) -> str:
    changes = [_number(item.get("change_pct")) for item in indices]
    valid = [value for value in changes if value is not None]
    if not valid:
        return "UNKNOWN"
    avg_change = sum(valid) / len(valid)
    if avg_change > 1:
        return "RISK_ON"
    if avg_change < -1:
        return "RISK_OFF"
    return "RANGE"


def _clean_stock_symbol(value: str) -> str:
    stripped = value.strip()
    if stripped[:2].lower() in {"sh", "sz", "bj"}:
        return stripped[2:]
    return stripped


def _exchange_from_prefixed_symbol(raw_symbol: str, symbol: str) -> str:
    prefix = raw_symbol.strip()[:2].lower()
    if prefix == "bj":
        return "BSE"
    if prefix == "sh":
        return "SSE"
    if prefix == "sz":
        return "SZSE"
    return normalize_exchange(symbol)


# ── Research data row normalizers ──


def _fund_flow_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a sector fund-flow row from AkShare."""
    n = _normalize_record(row)
    period_prefix = _fund_flow_period_prefix(n)
    return {
        "id": n.get("id") or n.get("代码") or n.get("板块代码") or n.get("code"),
        "name": n.get("名称") or n.get("板块") or n.get("name"),
        "code": n.get("代码") or n.get("板块代码") or n.get("code"),
        "trade_date": n.get("trade_date") or n.get("日期"),
        "source_updated_at": n.get("source_updated_at"),
        "period": n.get("period"),
        "rank": _int_value(n.get("rank") or n.get("序号")),
        "rise_count": _int_value(n.get("上涨家数") or n.get("rise_count")),
        "fall_count": _int_value(n.get("下跌家数") or n.get("fall_count")),
        "flat_count": _int_value(n.get("平盘家数") or n.get("flat_count")),
        "change_pct": _number(_period_value(n, period_prefix, "涨跌幅") or n.get("涨跌幅")),
        "main_net_inflow": _number(
            _period_value(n, period_prefix, "主力净流入-净额")
            or n.get("主力净流入-净额")
            or n.get("今日主力净流入")
            or n.get("主力净流入")
            or n.get("净额")
        ),
        "main_net_inflow_pct": _number(
            _period_value(n, period_prefix, "主力净流入-净占比")
            or n.get("主力净流入-净占比")
            or n.get("今日主力净流入占比")
        ),
        "super_large_net_inflow": _number(_period_value(n, period_prefix, "超大单净流入-净额") or n.get("超大单净流入-净额")),
        "large_net_inflow": _number(_period_value(n, period_prefix, "大单净流入-净额") or n.get("大单净流入-净额")),
        "medium_net_inflow": _number(_period_value(n, period_prefix, "中单净流入-净额") or n.get("中单净流入-净额")),
        "small_net_inflow": _number(_period_value(n, period_prefix, "小单净流入-净额") or n.get("小单净流入-净额")),
        "leader_stock": _period_value(n, period_prefix, "主力净流入最大股"),
        "leader_stock_code": _period_value(n, period_prefix, "主力净流入最大股代码"),
        "source": n.get("source"),
        "raw": n,
    }


def _fund_flow_period_prefix(row: dict[str, Any]) -> str:
    period = str(row.get("period") or "").strip()
    if period in {"今日", "5日", "10日"}:
        return period
    for prefix in ("今日", "5日", "10日", "3日", "20日"):
        if any(str(key).startswith(prefix) for key in row):
            return prefix
    return ""


def _period_value(row: dict[str, Any], prefix: str, suffix: str) -> Any:
    if prefix:
        value = row.get(f"{prefix}{suffix}")
        if value is not None:
            return value
    if prefix == "今日":
        value = row.get(f"今天{suffix}")
        if value is not None:
            return value
    return row.get(suffix)


def _stock_fund_flow_row_to_api(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Normalize an individual stock fund-flow row from AkShare."""
    n = _normalize_record(row)
    raw_symbol = str(n.get("代码") or n.get("股票代码") or n.get("code") or symbol).strip()
    clean = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, clean)
    return {
        "symbol": clean,
        "exchange": exchange,
        "vt_symbol": vt_symbol(clean, exchange),
        "name": n.get("名称") or n.get("股票简称") or n.get("name"),
        "change_pct": _number(n.get("涨跌幅") or n.get("今日涨跌幅") or n.get("今日排行榜-今日涨跌")),
        "main_net_inflow": _number(
            n.get("主力净流入-净额")
            or n.get("今日主力净流入")
            or n.get("主力净流入")
            or n.get("净额")
            or n.get("资金流入净额")
            or n.get("今日排行榜-主力净额")
        ),
        "main_net_inflow_pct": _number(
            n.get("主力净流入-净占比")
            or n.get("今日主力净流入占比")
            or n.get("今日排行榜-主力净占比")
        ),
        "super_large_net_inflow": _number(n.get("超大单净流入-净额")),
        "large_net_inflow": _number(n.get("大单净流入-净额")),
        "medium_net_inflow": _number(n.get("中单净流入-净额")),
        "small_net_inflow": _number(n.get("小单净流入-净额")),
        "main_rank": _int_value(n.get("今日排行榜-今日排名")),
        "main_rank_5d": _int_value(n.get("5日排行榜-5日排名")),
        "main_rank_10d": _int_value(n.get("10日排行榜-10日排名")),
        "raw": n,
    }


def _zt_pool_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a limit-up/limit-down pool row from AkShare."""
    n = _normalize_record(row)
    raw_symbol = str(n.get("代码") or n.get("code") or "").strip()
    clean = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, clean)
    return {
        "symbol": clean,
        "exchange": exchange,
        "vt_symbol": vt_symbol(clean, exchange),
        "name": n.get("名称") or n.get("name"),
        "close_price": _number(n.get("最新价") or n.get("收盘价") or n.get("涨停价")),
        "change_pct": _number(n.get("涨跌幅") or n.get("涨跌幅_乖离率")),
        "limit_up_price": _number(n.get("涨停价")),
        "volume_ratio": _number(n.get("量比") or n.get("封板量比")),
        "turnover_rate": _number(n.get("换手率") or n.get("换手率_换手率")),
        "first_limit_time": n.get("首次封板时间") or n.get("涨停时间"),
        "last_limit_time": n.get("最后封板时间"),
        "limit_up_count": _int_value(n.get("连板数") or n.get("连续涨停天数")),
        "limit_amount": _number(n.get("封板资金") or n.get("涨停封单量")),
        "raw": n,
    }


def _hot_rank_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a stock hot-rank row from AkShare."""
    n = _normalize_record(row)
    raw_symbol = str(n.get("股票代码") or n.get("代码") or n.get("code") or "").strip()
    clean = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, clean)
    return {
        "symbol": clean,
        "exchange": exchange,
        "vt_symbol": vt_symbol(clean, exchange),
        "name": n.get("股票名称") or n.get("名称") or n.get("name"),
        "rank": _int_value(n.get("当前排名") or n.get("排名")),
        "rank_change": _number(n.get("排名较昨日变化")),
        "hot_score": _number(n.get("个股热度")),
        "raw": n,
    }


def _lhb_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a dragon-tiger board (龙虎榜) row from AkShare."""
    n = _normalize_record(row)
    raw_symbol = str(n.get("代码") or n.get("code") or "").strip()
    clean = _clean_stock_symbol(raw_symbol)
    exchange = _exchange_from_prefixed_symbol(raw_symbol, clean)
    return {
        "symbol": clean,
        "exchange": exchange,
        "vt_symbol": vt_symbol(clean, exchange),
        "name": n.get("名称") or n.get("name"),
        "trade_date": n.get("交易日期") or n.get("上榜日期") or n.get("上榜日") or n.get("日期"),
        "close_price": _number(n.get("收盘价")),
        "change_pct": _number(n.get("涨跌幅")),
        "turnover_rate": _number(n.get("换手率")),
        "buy_amount": _number(n.get("买入额") or n.get("买入金额") or n.get("龙虎榜买入额")),
        "sell_amount": _number(n.get("卖出额") or n.get("卖出金额") or n.get("龙虎榜卖出额")),
        "net_buy": _number(n.get("净额") or n.get("净买入额") or n.get("龙虎榜净买额")),
        "reason": n.get("上榜原因") or n.get("上榜理由") or n.get("解读"),
        "broker_count": _int_value(n.get("营业部数")),
        "raw": n,
    }


def _notice_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a stock notice/announcement row from AkShare."""
    n = _normalize_record(row)
    return {
        "title": n.get("公告标题") or n.get("标题") or n.get("title"),
        "date": n.get("公告日期") or n.get("日期") or n.get("date"),
        "type": n.get("公告类型") or n.get("类型"),
        "url": n.get("公告链接") or n.get("url") or n.get("链接"),
        "pdf_url": n.get("pdf链接") or n.get("附件链接"),
        "raw": n,
    }


def _financial_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a quarterly financial report row from AkShare.

    AkShare's ``stock_profit_sheet_by_quarterly_em`` returns English uppercase
    column names (OPERATE_INCOME, NETPROFIT, …) while some older / alternative
    data sources use Chinese names.  We try both conventions so the mapping
    works regardless of the source.
    """
    n = _normalize_record(row)
    report_date = n.get("报告期") or n.get("截止日期") or n.get("REPORT_DATE")
    publish_date = n.get("公告日期") or n.get("披露日期") or n.get("NOTICE_DATE") or n.get("UPDATE_DATE")
    return {
        "report_date": report_date,
        "publish_date": publish_date,
        "revenue": _number(
            n.get("营业总收入")
            or n.get("TOTAL_OPERATE_INCOME")
            or n.get("OPERATE_INCOME"),
        ),
        "revenue_yoy": _number(
            _first_present(
                n.get("营业总收入同比增长"),
                n.get("营业总收入同比增长率"),
            ),
        ),
        "revenue_qoq": _number(
            _first_present(
                n.get("营业总收入季度环比增长"),
                n.get("TOTAL_OPERATE_INCOME_QOQ"),
                n.get("OPERATE_INCOME_QOQ"),
            ),
        ),
        "net_profit": _number(
            _first_present(
                n.get("归属于母公司股东的净利润"),
                n.get("PARENT_NETPROFIT"),
                n.get("净利润"),
                n.get("NETPROFIT"),
            ),
        ),
        "net_profit_yoy": _number(
            _first_present(
                n.get("归母净利润同比增长"),
                n.get("净利润同比增长"),
                n.get("净利润同比增长率"),
            ),
        ),
        "net_profit_qoq": _number(
            _first_present(
                n.get("归母净利润季度环比增长"),
                n.get("PARENT_NETPROFIT_QOQ"),
                n.get("NETPROFIT_QOQ"),
            ),
        ),
        "gross_margin": _number(
            n.get("销售毛利率"),
        ),
        "net_margin": _number(
            n.get("销售净利率"),
        ),
        "eps": _number(
            n.get("每股收益")
            or n.get("基本每股收益")
            or n.get("BASIC_EPS"),
        ),
        "roe": _number(
            n.get("净资产收益率")
            or n.get("加权净资产收益率"),
        ),
        "deducted_net_profit": _number(n.get("扣非净利润") or n.get("DEDUCT_PARENT_NETPROFIT")),
        "operating_cash_flow": _number(n.get("经营活动产生的现金流量净额") or n.get("NETCASH_OPERATE")),
        "raw": n,
    }


def _financial_performance_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize Eastmoney's market-wide performance report by raw field name."""

    n = _normalize_record(row)
    symbol = str(n.get("SECURITY_CODE") or "").strip()
    secucode = str(n.get("SECUCODE") or "").strip().upper()
    exchange_hint = secucode.rsplit(".", 1)[-1] if "." in secucode else None
    exchange = normalize_exchange(symbol, exchange_hint)
    net_profit = _number(n.get("PARENT_NETPROFIT"))
    revenue = _number(n.get("TOTAL_OPERATE_INCOME"))
    eps = _number(n.get("BASIC_EPS"))
    cash_flow_per_share = _number(n.get("MGJYXJJE"))
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": vt_symbol(symbol, exchange) if symbol else None,
        "name": n.get("SECURITY_NAME_ABBR"),
        "report_date": _financial_storage_timestamp(n.get("REPORTDATE")),
        "publish_date": _financial_storage_timestamp(
            _first_present(n.get("NOTICE_DATE"), n.get("UPDATE_DATE"))
        ),
        "revenue": revenue,
        "revenue_yoy": _number(n.get("YSTZ")),
        "revenue_qoq": _number(n.get("YSHZ")),
        "net_profit": net_profit,
        "net_profit_yoy": _number(n.get("SJLTZ")),
        "net_profit_qoq": _number(n.get("SJLHZ")),
        "deducted_net_profit": _number(n.get("DEDUCT_PARENT_NETPROFIT")),
        "eps": eps,
        "gross_margin": _number(n.get("XSMLL")),
        "net_margin": _financial_ratio_pct(net_profit, revenue),
        "roe": _number(n.get("WEIGHTAVG_ROE")),
        "cash_flow_quality": _financial_ratio(cash_flow_per_share, eps),
        "source": "eastmoney.RPT_LICO_FN_CPD",
        "raw": n,
    }


def _financial_report_date(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value or "").strip()[:10]
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Invalid financial report date: {value!r}")
    if (parsed.month, parsed.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        raise ValueError(f"Financial report date is not a quarter end: {parsed.isoformat()}")
    return parsed.isoformat()


def _financial_storage_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        return text
    return f"{parsed.isoformat()} 00:00:00"


def _financial_ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_value = _number(numerator)
    denominator_value = _number(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return round(float(numerator_value) / float(denominator_value), 4)


def _financial_ratio_pct(numerator: Any, denominator: Any) -> float | None:
    numerator_value = _number(numerator)
    denominator_value = _number(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return round(float(numerator_value) / float(denominator_value) * 100, 4)


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "", "-", "--")), None)


def _indicator_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a financial analysis indicator row from AkShare (Sina source)."""
    n = _normalize_record(row)
    return {
        "report_date": n.get("日期") or n.get("date"),
        "eps": _number(n.get("每股收益")),
        "bps": _number(n.get("每股净资产")),
        "roe": _number(n.get("净资产收益率")),
        "gross_margin": _number(n.get("销售毛利率")),
        "net_margin": _number(n.get("销售净利率")),
        "current_ratio": _number(n.get("流动比率")),
        "quick_ratio": _number(n.get("速动比率")),
        "debt_ratio": _number(n.get("资产负债率")),
        "receivable_turnover": _number(n.get("应收账款周转率")),
        "inventory_turnover": _number(n.get("存货周转率")),
        "raw": n,
    }


def _number(value: Any) -> float | int | None:
    value = _json_value(value)
    if value in (None, "", "-", "--"):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _first_number(row: dict[str, Any], *keys: str) -> float | int | None:
    for key in keys:
        if key in row:
            value = _number(row.get(key))
            if value is not None:
                return value
    return None


def _payload_count(payload: Any) -> int | None:
    if isinstance(payload, AkShareSourceInfo):
        return 1
    if isinstance(payload, dict):
        total = payload.get("total")
        if isinstance(total, int):
            return total
        items = payload.get("items")
        if isinstance(items, list):
            return len(items)
    return None


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _first_payload_item(payload: Any) -> dict[str, Any]:
    items = _payload_items(payload)
    if not items:
        return {}
    return items[0]


def _payload_sample(payload: Any) -> Any:
    if isinstance(payload, AkShareSourceInfo):
        return payload.to_api()
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items[:2]
    return None
