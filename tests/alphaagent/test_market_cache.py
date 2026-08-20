from copy import copy

import pytest

from alphaagent.market.cache import TTLCache


class DeepCopyGuard:
    def __deepcopy__(self, _memo):
        raise AssertionError("nested report values must not be deep-copied")


class SharedBackend:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.values.get(key)

    def set(self, key: str, value: object, _ttl_seconds: float) -> None:
        self.values[key] = value

    def discard_prefix(self, prefix: str) -> None:
        for key in list(self.values):
            if key.startswith(prefix):
                self.values.pop(key)

    def clear(self) -> None:
        self.values.clear()


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


def test_ttl_cache_discard_prefix_drops_only_matching_keys() -> None:
    cache = TTLCache()
    cache.get_or_set("review:2026-08-12:v1:v1", 60, lambda: {"rows": [1]})
    cache.get_or_set("review:2026-08-12:v2:v1", 60, lambda: {"rows": [2]})
    cache.get_or_set("review:2026-08-11:v1:v1", 60, lambda: {"rows": [3]})

    cache.discard_prefix("review:2026-08-12:")  # 该日全部版本 key 失效
    cache.discard_prefix("review:2026-08-10:")  # 无匹配前缀静默跳过

    reloads: list[str] = []
    reloaded_v1 = cache.get_or_set(
        "review:2026-08-12:v1:v1",
        60,
        lambda: reloads.append("v1") or {"rows": [4]},
    )
    reloaded_v2 = cache.get_or_set(
        "review:2026-08-12:v2:v1",
        60,
        lambda: reloads.append("v2") or {"rows": [5]},
    )
    kept = cache.get_or_set(
        "review:2026-08-11:v1:v1",
        60,
        lambda: pytest.fail("untargeted cache entry unexpectedly reloaded"),
    )

    assert reloaded_v1 == {"rows": [4]}
    assert reloaded_v2 == {"rows": [5]}
    assert reloads == ["v1", "v2"]
    assert kept == {"rows": [3]}


def test_ttl_cache_reads_values_populated_by_another_process_cache() -> None:
    backend = SharedBackend()
    writer = TTLCache(backend=backend)
    reader = TTLCache(backend=backend)

    writer.get_or_set("market:overview", 60, lambda: {"source": "worker"})
    payload = reader.get_or_set(
        "market:overview",
        60,
        lambda: pytest.fail("shared cache value unexpectedly reloaded"),
    )

    assert payload == {"source": "worker"}
