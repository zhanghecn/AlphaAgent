from alphaagent.market import warmup
from alphaagent.market.cache import TTLCache


def test_periodic_market_warmup_does_not_duplicate_stock_list_reads() -> None:
    task_names = {task.name for task in warmup._warmup_tasks()}

    assert not {
        "stock_list_mktcap",
        "stock_list_change",
        "stock_list_turnover",
    } & task_names


def test_periodic_market_warmup_only_loads_expired_entries(monkeypatch) -> None:
    calls: list[object] = []
    client = object()
    task = warmup.WarmupTask(
        name="quotes",
        cache_key="quotes",
        ttl_seconds=60,
        loader=lambda current: calls.append(current) or {"status": "ready"},
        refresh=True,
    )
    monkeypatch.setattr(warmup, "market_cache", TTLCache())
    monkeypatch.setattr(
        warmup,
        "RealMarketDataClient",
        lambda timeout: client,
    )

    warmup._refresh_market_cache_once(8.0, [task])
    warmup._refresh_market_cache_once(8.0, [task])

    assert calls == [client]


def test_periodic_market_warmup_stops_outside_trading_hours(monkeypatch) -> None:
    def fail_refresh(*_args) -> None:
        raise AssertionError("outside-hours refresh must not run")

    monkeypatch.setattr(warmup, "_is_intraday_china", lambda: False)
    monkeypatch.setattr(warmup, "_refresh_market_cache_once", fail_refresh)

    warmup._refresh_market_cache_tick(8.0, list(warmup._warmup_tasks()))


def test_initial_market_warmup_stops_outside_trading_hours(monkeypatch) -> None:
    def fail_warmup(*_args) -> None:
        raise AssertionError("outside-hours initial warmup must not run")

    monkeypatch.setattr(warmup, "_is_intraday_china", lambda: False)
    monkeypatch.setattr(warmup, "_run_warmup_task", fail_warmup)

    warmup._warm_initial_market_cache(8.0, list(warmup._warmup_tasks()))
