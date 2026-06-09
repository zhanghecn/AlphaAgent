"""Small in-process TTL cache for public market-data reads."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass
class _CacheEntry:
    expires_at: float
    value: object


class TTLCache:
    """Thread-safe cache with per-key request coalescing."""

    def __init__(self, max_items: int = 512) -> None:
        self.max_items = max_items
        self._entries: dict[str, _CacheEntry] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T:
        if ttl_seconds <= 0:
            return loader()

        now = time.monotonic()
        cached = self._get_fresh(key, now)
        if cached is not None:
            return copy.deepcopy(cached)

        key_lock = self._key_lock(key)
        with key_lock:
            now = time.monotonic()
            cached = self._get_fresh(key, now)
            if cached is not None:
                return copy.deepcopy(cached)

            value = loader()
            self._set(key, value, now + ttl_seconds)
            return copy.deepcopy(value)

    def refresh(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T:
        """Recompute a cache value under the per-key lock."""

        if ttl_seconds <= 0:
            return loader()

        key_lock = self._key_lock(key)
        with key_lock:
            value = loader()
            self._set(key, value, time.monotonic() + ttl_seconds)
            return copy.deepcopy(value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._locks.clear()

    def _get_fresh(self, key: str, now: float) -> object | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            return entry.value

    def _set(self, key: str, value: object, expires_at: float) -> None:
        with self._lock:
            if len(self._entries) >= self.max_items:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = _CacheEntry(expires_at=expires_at, value=copy.deepcopy(value))

    def _key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock


market_cache = TTLCache(max_items=2048)
