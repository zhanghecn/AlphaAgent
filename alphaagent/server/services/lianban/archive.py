"""东财涨停池五池每日盘后归档。

盘后调 AkShareAdapter.limit_up_pools(per_pool_limit=None 全量)拉取涨停(zt)/
炸板(zbgc)/跌停(dtgc)/昨日涨停(zt_previous)/强势股(strong)五池, 落库
limit_up_pool_snapshots。

口径:
- 幂等: 当日每池先 delete(trade_date+pool_type) 再 insert, 重复跑结果一致。
- 不可用池不抹数据: 池 status=="unavailable" 或池 key 缺失(视同不可用)→
  整个跳过(不 delete 不 insert), 保留旧归档, 并在返回的 "unavailable" 列表
  透出; 池正常返回但 items 为空 → delete+insert 0 行(明确的"当日无数据")。
- 归档全量, 不做主板/ST 过滤(过滤在查询层)。
- 非交易日/东财窗口外(~3 周前)日期: 各池正常返回空 → 写 0 行, 不报错。
- first/last_limit_time 由适配器 _zt_pool_row_to_api 统一规范成 "HH:MM:SS",
  本层只透传(None/空串容错为 None); raw["涨停统计"] "13/9" 拆为
  limit_stat_days=13 / limit_stat_boards=9。
- 防御: 池 total > len(items)(仍被截断)时行照写, 在 "truncated" 列表透出告警。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, insert

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.db import schema as db_schema

POOL_TYPES = ("zt", "zbgc", "dtgc", "zt_previous", "strong")

# 跨模块契约(B4 API live 分流复用): 五池类型/默认 source/行映射函数公开。
DEFAULT_SOURCE = "akshare.stock_ztb_em"


def _time_text_or_none(value: Any) -> str | None:
    """透传适配器已规范的 "HH:MM:SS"; None/空串 → None。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_limit_stat(value: Any) -> tuple[int | None, int | None]:
    """涨停统计 "13/9" → (13, 9); 无斜杠 → (None, None); 单段失败该段 None。"""
    text = str(value or "").strip()
    if "/" not in text:
        return None, None
    left, _, right = text.partition("/")

    def _int(part: str) -> int | None:
        try:
            return int(part.strip())
        except (TypeError, ValueError):
            return None

    return _int(left), _int(right)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pool_row(
    trade_date: date, pool_type: str, item: dict, source: str
) -> dict[str, Any]:
    """适配器规范化后的 item → limit_up_pool_snapshots 行。

    直取字段来自 item 顶层; break_count/limit_stat/industry/amount 只存在于
    item["raw"](东财原始行), 解析失败一律 None 容错。
    """
    raw = item.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    stat_days, stat_boards = _parse_limit_stat(raw.get("涨停统计"))
    vt_symbol = str(item.get("vt_symbol") or "").strip()
    name = str(item.get("name") or "").strip() or vt_symbol
    industry = raw.get("所属行业")
    industry_text = str(industry).strip() if industry is not None else ""
    return {
        "trade_date": trade_date,
        "pool_type": pool_type,
        "vt_symbol": vt_symbol,
        "name": name,
        "close_price": _float_or_none(item.get("close_price")),
        "change_pct": _float_or_none(item.get("change_pct")),
        "turnover_rate": _float_or_none(item.get("turnover_rate")),
        "volume_ratio": _float_or_none(item.get("volume_ratio")),
        "limit_amount": _float_or_none(item.get("limit_amount")),
        "first_limit_time": _time_text_or_none(item.get("first_limit_time")),
        "last_limit_time": _time_text_or_none(item.get("last_limit_time")),
        "break_count": _int_or_none(raw.get("炸板次数")),
        "limit_stat_days": stat_days,
        "limit_stat_boards": stat_boards,
        "limit_up_count": _int_or_none(item.get("limit_up_count")),
        "industry": industry_text or None,
        "amount": _float_or_none(raw.get("成交额")),
        "source": source,
        "raw": raw,
    }


def archive_daily_pools(
    session,
    trade_date: date,
    *,
    adapter: Any = None,
    include_news: bool = True,
) -> dict[str, Any]:
    """归档 trade_date 当日五池到 limit_up_pool_snapshots。

    当日每池先 delete(trade_date+pool_type) 再 insert(幂等); 不可用/缺失的池
    整个跳过(保留旧数据); 正常但空的池显式写 0 行。返回 {"trade_date": iso,
    "pools": {"zt": n, ...}, "rows_written": n, "unavailable": [...],
    "truncated": [...]}。
    """
    adapter = adapter if adapter is not None else AkShareAdapter()
    payload = adapter.limit_up_pools(trade_date.strftime("%Y%m%d"), per_pool_limit=None)
    source = str(payload.get("source") or DEFAULT_SOURCE)
    pools_payload = payload.get("pools") or {}
    table = db_schema.limit_up_pool_snapshots

    pool_counts: dict[str, int] = {}
    unavailable: list[str] = []
    truncated: list[str] = []
    rows_written = 0
    for pool_type in POOL_TYPES:
        pool = pools_payload.get(pool_type)
        if not isinstance(pool, dict) or pool.get("status") == "unavailable":
            # 池缺失视同不可用: 跳过, 不 delete 不 insert, 保留旧归档。
            unavailable.append(pool_type)
            pool_counts[pool_type] = 0
            continue
        session.execute(
            delete(table).where(
                table.c.trade_date == trade_date,
                table.c.pool_type == pool_type,
            )
        )
        items = pool.get("items") or []
        total = _int_or_none(pool.get("total"))
        if total is not None and total > len(items):
            truncated.append(pool_type)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            vt_symbol = str(item.get("vt_symbol") or "").strip()
            if not vt_symbol or vt_symbol in seen:
                continue
            seen.add(vt_symbol)
            rows.append(pool_row(trade_date, pool_type, item, source))
        if rows:
            session.execute(insert(table), rows)
        pool_counts[pool_type] = len(rows)
        rows_written += len(rows)

    result = {
        "trade_date": trade_date.isoformat(),
        "pools": pool_counts,
        "rows_written": rows_written,
        "unavailable": unavailable,
        "truncated": truncated,
    }
    # 驱动新闻抓取逐股访问外部源，盘中快照只更新五池本身，盘后才执行。
    if include_news:
        try:
            from alphaagent.server.services.lianban.news_driver import sync_zt_news

            result["news"] = sync_zt_news(session, trade_date, adapter=adapter)
        except Exception as exc:  # noqa: BLE001 - 增强路径降级
            result["news"] = {"error": exc.__class__.__name__}
    return result
