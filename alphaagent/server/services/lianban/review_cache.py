"""连板复盘 payload 进程缓存(API 层与归档/重建任务共享)。

final/rebuild 模式且 trade_date < 今日(中国时区)的 payload 不可变 → 长 TTL
进程缓存兜底复盘页 P95; live 模式不缓存(适配器层已有 TTL),"今日 final"
也不缓存(盘后可能补偿重归档/重建)。

跨进程失效(版本戳): 缓存 key 带该日两表 max(updated_at) 版本戳 ——
归档/重建/回补在任何进程落库后, updated_at 前进 → key 变 → 下次请求自然
miss 回源。每次请求(含缓存命中路径)先跑两条 max(updated_at) 索引轻查询
(~1ms)取版本。正确性不依赖 invalidate_lianban_cache(真实部署里同步
worker 与 api 是分离进程, 单进程 dict 失效信号过不去)。

失效函数(同进程防御): 归档/重建/回补任务成功落库后调
invalidate_lianban_cache()(data_sync.py 三个 runner 已接线)。按日定向
失效用前缀删(版本化 key 无法由日期反推完整 key)。版本演进会遗留孤儿
key, 容量上限 + FIFO 驱逐兜底, 无需主动清理。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from alphaagent.market.cache import TTLCache

REVIEW_CACHE_TTL_SECONDS = 24 * 3600
REVIEW_CACHE_MAX_ITEMS = 500

review_payload_cache: TTLCache = TTLCache(max_items=REVIEW_CACHE_MAX_ITEMS)


def version_stamp(value: Any) -> str:
    """max(updated_at) → 版本戳字符串; 无数据(None) → "none"。"""
    return "none" if value is None else str(value)


def review_cache_prefix(trade_date: date) -> str:
    return f"lianban:review:{trade_date.isoformat()}:"


def review_cache_key(
    trade_date: date, version_pool: str, version_daily: str
) -> str:
    """版本化缓存 key: 日期前缀 + 归档/重建两表 updated_at 版本戳。"""
    return f"{review_cache_prefix(trade_date)}{version_pool}:{version_daily}"


def invalidate_lianban_cache(trade_date: date | None = None) -> None:
    """归档/重建/回补落库后调用(同进程防御); None(默认)清空全部,
    指定日期按前缀删除该日的全部版本 key。"""
    if trade_date is None:
        review_payload_cache.clear()
    else:
        review_payload_cache.discard_prefix(review_cache_prefix(trade_date))
