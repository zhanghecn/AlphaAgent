from copy import copy

import pytest

from alphaagent.market.cache import TTLCache


class DeepCopyGuard:
    def __deepcopy__(self, _memo):
        raise AssertionError("nested report values must not be deep-copied")


def test_ttl_cache_deeply_isolates_values_by_default() -> None:
    cache = TTLCache()
    first = cache.get_or_set("default", 60, lambda: {"rows": []})

    first["rows"].append("caller mutation")
    second = cache.get_or_set(
        "default",
        60,
        lambda: pytest.fail("fresh cache entry unexpectedly reloaded"),
    )

    assert second == {"rows": []}


def test_ttl_cache_custom_copier_can_keep_nested_values_shared() -> None:
    cache = TTLCache(copier=copy)
    guard = DeepCopyGuard()

    first = cache.get_or_set("report", 60, lambda: {"guard": guard})
    second = cache.get_or_set(
        "report",
        60,
        lambda: pytest.fail("fresh cache entry unexpectedly reloaded"),
    )

    assert first is not second
    assert first["guard"] is second["guard"] is guard


def test_ttl_cache_get_reads_a_fresh_value_without_running_a_loader() -> None:
    cache = TTLCache()
    cache.get_or_set("report", 60, lambda: {"rows": []})

    first = cache.get("report")
    assert first == {"rows": []}
    first["rows"].append("caller mutation")

    assert cache.get("report") == {"rows": []}
