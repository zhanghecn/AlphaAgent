"""Background cache warmup for interactive market-data pages."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from alphaagent.market.cache import market_cache
from alphaagent.market.providers import RealMarketDataClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WarmupTask:
    name: str
    cache_key: str | Callable[[RealMarketDataClient], str]
    ttl_seconds: float
    loader: Callable[[RealMarketDataClient], Any]
    refresh: bool = False


def start_market_cache_warmup(timeout: float = 8.0) -> None:
    thread = threading.Thread(target=_warm_market_cache, args=(timeout,), daemon=True)
    thread.start()


def _warm_market_cache(timeout: float) -> None:
    tasks = _warmup_tasks()
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="market-warmup") as executor:
        futures = {
            executor.submit(_run_warmup_task, timeout, task): task.name
            for task in tasks
        }
        for future, name in futures.items():
            try:
                future.result()
            except Exception as exc:
                LOGGER.info("market cache warmup skipped %s: %s", name, exc.__class__.__name__)

    refresh_tasks = [task for task in tasks if task.refresh]
    if refresh_tasks:
        threading.Thread(target=_refresh_market_cache, args=(timeout, refresh_tasks), daemon=True).start()


def _warmup_tasks() -> tuple[WarmupTask, ...]:
    return (
        WarmupTask("indices", "indices", 10, lambda client: client._get_indices_uncached(), refresh=True),
        WarmupTask("market_overview", "market_overview", 30, lambda client: client._market_overview_uncached(), refresh=True),
        WarmupTask("stock_list_mktcap", "list_stocks:1:50:mktcap", 10, lambda client: client._list_stocks_uncached(1, 50, "mktcap"), refresh=True),
        WarmupTask("stock_list_change", "list_stocks:1:50:changepercent", 10, lambda client: client._list_stocks_uncached(1, 50, "changepercent"), refresh=True),
        WarmupTask("stock_list_turnover", "list_stocks:1:50:amount", 10, lambda client: client._list_stocks_uncached(1, 50, "amount"), refresh=True),
        WarmupTask("stock_bars_sample", _sample_stock_bar_cache_key, 600, _warm_sample_stock_bars),
        WarmupTask("index_bars_sample", _sample_index_bar_cache_key, 600, _warm_sample_index_bars),
        WarmupTask("sectors_industry", "list_sectors:industry", 86400, lambda client: client._list_sectors_uncached("industry")),
        WarmupTask("sectors_concept", "list_sectors:concept", 86400, lambda client: client._list_sectors_uncached("concept")),
        WarmupTask("industry_chains_seed", "dynamic_industry_chains:12:40", 300, _warm_dynamic_industry_chains),
        WarmupTask("sector_graph_default", "sector_relation_graph::12:50", 300, lambda client: _warm_sector_relation_graph(client, "")),
        WarmupTask("source_status", "source_status", 60, lambda client: client._source_status_uncached()),
    )


def _run_warmup_task(timeout: float, task: WarmupTask) -> None:
    client = RealMarketDataClient(timeout=timeout)
    cache_key = task.cache_key(client) if callable(task.cache_key) else task.cache_key
    market_cache.refresh(cache_key, task.ttl_seconds, lambda: task.loader(client))


def _refresh_market_cache(timeout: float, tasks: list[WarmupTask]) -> None:
    while True:
        time.sleep(8)
        client = RealMarketDataClient(timeout=timeout)
        for task in tasks:
            try:
                cache_key = task.cache_key(client) if callable(task.cache_key) else task.cache_key
                market_cache.refresh(cache_key, task.ttl_seconds, lambda task=task: task.loader(client))
            except Exception as exc:
                LOGGER.info("market cache refresh skipped %s: %s", task.name, exc.__class__.__name__)


def _warm_dynamic_industry_chains(client: RealMarketDataClient) -> dict[str, Any]:
    from alphaagent.server.api.industry_chains import discover_dynamic_industry_chains

    return discover_dynamic_industry_chains(client, limit=12, page_size=40)


def _warm_sector_relation_graph(client: RealMarketDataClient, query: str) -> dict[str, Any]:
    from alphaagent.server.api.industry_chains import build_sector_relation_graph

    return build_sector_relation_graph(client, query, limit=12, page_size=50)


def _warm_sample_stock_bars(client: RealMarketDataClient) -> dict[str, Any]:
    stock = _sample_stock(client)
    return client._stock_bars_uncached(str(stock["symbol"]), str(stock.get("exchange") or ""), 1800, "1d")


def _warm_sample_index_bars(client: RealMarketDataClient) -> dict[str, Any]:
    index = _sample_index(client)
    return client._stock_bars_uncached(str(index["symbol"]), str(index.get("exchange") or ""), 1800, "1d")


def _sample_stock_bar_cache_key(client: RealMarketDataClient) -> str:
    stock = _sample_stock(client)
    return f"stock_bars:{stock['symbol']}:{stock.get('exchange') or ''}:1d:1800"


def _sample_index_bar_cache_key(client: RealMarketDataClient) -> str:
    index = _sample_index(client)
    return f"stock_bars:{index['symbol']}:{index.get('exchange') or ''}:1d:1800"


def _sample_stock(client: RealMarketDataClient) -> dict[str, Any]:
    items = client.list_stocks(page=1, page_size=1, sort="amount").get("items") or []
    if not items or not isinstance(items[0], dict) or not items[0].get("symbol"):
        raise RuntimeError("live stock list returned no sample symbol")
    return items[0]


def _sample_index(client: RealMarketDataClient) -> dict[str, Any]:
    quotes = [quote.to_api() for quote in client.get_indices()]
    if not quotes or not quotes[0].get("symbol"):
        raise RuntimeError("live index quotes returned no sample symbol")
    return quotes[0]
