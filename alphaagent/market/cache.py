"""Small in-process TTL cache for public market-data reads."""

from __future__ import annotations

import copy
from datetime import date, datetime
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar, cast

T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


class CacheBackend(Protocol):
    """Optional shared backing store for :class:`TTLCache`."""

    def get(self, key: str) -> object | None: ...

    def set(self, key: str, value: object, ttl_seconds: float) -> None: ...

    def discard_prefix(self, prefix: str) -> None: ...

    def clear(self) -> None: ...


class RedisJSONCacheBackend:
    """Redis-backed JSON cache scoped to AlphaAgent market-read entries."""

    def __init__(self, url: str, *, namespace: str = "alphaagent:market-cache:") -> None:
        import redis

        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        self._namespace = namespace

    def get(self, key: str) -> object | None:
        raw = self._client.get(self._storage_key(key))
        return None if raw is None else json.loads(raw)

    def set(self, key: str, value: object, ttl_seconds: float) -> None:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )
        self._client.set(self._storage_key(key), payload, ex=max(1, math.ceil(ttl_seconds)))

    def discard_prefix(self, prefix: str) -> None:
        self._delete_matching(f"{self._storage_key(prefix)}*")

    def clear(self) -> None:
        self._delete_matching(f"{self._namespace}*")

    def _storage_key(self, key: str) -> str:
        return f"{self._namespace}{key}"

    def _delete_matching(self, pattern: str) -> None:
        keys = list(self._client.scan_iter(match=pattern, count=200))
        if keys:
            self._client.delete(*keys)


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is not value:
            return scalar
    raise TypeError(f"{value.__class__.__name__} is not JSON serializable")


@dataclass
class _CacheEntry:
    expires_at: float
    value: object


class TTLCache:
    """Thread-safe cache with per-key request coalescing."""

    def __init__(
        self,
        max_items: int = 512,
        *,
        copier: Callable[[object], object] = copy.deepcopy,
        backend: CacheBackend | None = None,
    ) -> None:
        self.max_items = max_items
        self._copier = copier
        self._backend = backend
        self._entries: dict[str, _CacheEntry] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T:
        if ttl_seconds <= 0:
            return loader()

        now = time.monotonic()
        cached = self._get_fresh(key, now)
        if cached is not None:
            return self._copy(cached)
        cached = self._get_shared(key)
        if cached is not None:
            return self._copy(cached)

        key_lock = self._key_lock(key)
        with key_lock:
            now = time.monotonic()
            cached = self._get_fresh(key, now)
            if cached is not None:
                return self._copy(cached)
            cached = self._get_shared(key)
            if cached is not None:
                return self._copy(cached)

            value = loader()
            self._set(key, value, now + ttl_seconds, ttl_seconds)
            return self._copy(value)

    def get(self, key: str) -> T | None:
        """Return a fresh cached value without running a loader."""

        cached = self._get_fresh(key, time.monotonic())
        if cached is not None:
            return self._copy(cached)
        cached = self._get_shared(key)
        return None if cached is None else self._copy(cached)

    def refresh(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T:
        """Recompute a cache value under the per-key lock."""

        if ttl_seconds <= 0:
            return loader()

        key_lock = self._key_lock(key)
        with key_lock:
            value = loader()
            self._set(key, value, time.monotonic() + ttl_seconds, ttl_seconds)
            return self._copy(value)

    def set_backend(self, backend: CacheBackend | None) -> None:
        """Replace the shared backend and discard local entries from the old mode."""

        with self._lock:
            self._backend = backend
            self._entries.clear()
            self._locks.clear()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._locks.clear()
            backend = self._backend
        if backend is not None:
            self._call_backend(backend.clear)

    def discard_prefix(self, prefix: str) -> None:
        """Drop every cached key starting with prefix (versioned-key invalidation)."""

        with self._lock:
            stale = [key for key in self._entries if key.startswith(prefix)]
            for key in stale:
                self._entries.pop(key, None)
                self._locks.pop(key, None)
            backend = self._backend
        if backend is not None:
            self._call_backend(lambda: backend.discard_prefix(prefix))

    def _get_fresh(self, key: str, now: float) -> object | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            return entry.value

    def _set(
        self,
        key: str,
        value: object,
        expires_at: float,
        ttl_seconds: float,
    ) -> None:
        with self._lock:
            if len(self._entries) >= self.max_items:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = _CacheEntry(
                expires_at=expires_at,
                value=self._copy(value),
            )
            backend = self._backend
        if backend is not None:
            self._call_backend(lambda: backend.set(key, value, ttl_seconds))

    def _get_shared(self, key: str) -> object | None:
        with self._lock:
            backend = self._backend
        if backend is None:
            return None
        try:
            return backend.get(key)
        except Exception as exc:  # noqa: BLE001 - local cache remains the fallback
            LOGGER.debug("shared market cache read skipped: %s", exc.__class__.__name__)
            return None

    def _call_backend(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001 - local cache remains the fallback
            LOGGER.debug("shared market cache write skipped: %s", exc.__class__.__name__)

    def _copy(self, value: T) -> T:
        return cast(T, self._copier(value))

    def _key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock


market_cache = TTLCache(max_items=2048)


def configure_market_cache(redis_url: str) -> None:
    """Use Redis for shared market reads when it is configured and reachable."""

    url = redis_url.strip()
    if not url:
        market_cache.set_backend(None)
        return
    try:
        market_cache.set_backend(RedisJSONCacheBackend(url))
    except Exception as exc:  # noqa: BLE001 - startup must retain local cache fallback
        LOGGER.warning("shared market cache disabled: %s", exc.__class__.__name__)
        market_cache.set_backend(None)
