"""沪深融资余额每日同步。

数据源选型(2026-08-13 容器实测, akshare 1.18.64):
- 采用 akshare.economic.macro_china 的 macro_china_market_margin_sh /
  macro_china_market_margin_sz(金十聚合的交易所两融汇总)。一次请求各取全
  历史(~4k 行), 单位同为元, 列名一致, 日期列为 datetime.date。
- 与交易所官网口径对账一致: macro_sh 2026-08-12 融资余额 1355236713043 ==
  stock_margin_sse 同日; macro_sz 2026-08-11 1.279168e12 ==
  stock_margin_szse 单日 12791.68 亿。
- 弃用 stock_margin_sse/stock_margin_szse 组合: szse 仅单日粒度、单位是
  亿元、非交易日直接抛 ValueError, lookback 逐日循环既慢又要逐日容错;
  macro 接口批量同单位, 客户端过滤窗口即可。

口径:
- 两市合计只写沪/深同日都有的日期(单边未发布时不写, 合计不缺腿)。
- 同步窗口以共同最新日为锚向前 lookback_days 个自然日(锚定数据源最新日,
  不依赖本机时钟, 节假日与迟发布都能被补偿链接住)。
- 幂等: 窗口内按 trade_date delete+insert, 重复跑结果一致。
- 数据源异常(网络/接口变更/无 akshare) → 返回 rows_written=0 + error,
  不动旧数据, 不抛错(同 lianban archive 的容错风格)。
"""
from __future__ import annotations

import importlib
import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select

from alphaagent.data_sources.akshare_adapter import _akshare_network_env
from alphaagent.server.db import schema as db_schema

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE = "akshare.macro_china_market_margin"
_TABLE = db_schema.market_margin_balance


def _load_margin_module():
    """惰性 import akshare 宏观模块(宿主机/测试环境可无 akshare)。"""
    return importlib.import_module("akshare.economic.macro_china")


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # NaN/inf 不入库(深市部分列实测为 NaN)
    return result if math.isfinite(result) else None


def _coerce_date(value: Any) -> date | None:
    """宏观接口日期列容错: datetime.date / datetime / "2026-08-12" / "20260812"。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_balances(df: Any) -> dict[date, dict[str, float | None]]:
    """宏观接口 DataFrame → {trade_date: {balance/buy/total}}; 坏行跳过。"""
    out: dict[date, dict[str, float | None]] = {}
    if df is None:
        return out
    for record in df.to_dict("records"):
        trade_date = _coerce_date(record.get("日期"))
        balance = _float_or_none(record.get("融资余额"))
        if trade_date is None or balance is None:
            continue
        out[trade_date] = {
            "balance": balance,
            "buy": _float_or_none(record.get("融资买入额")),
            "total": _float_or_none(record.get("融资融券余额")),
        }
    return out


def sync_margin_balance(
    session, *, adapter: Any = None, lookback_days: int = 10
) -> dict[str, Any]:
    """拉取沪深融资余额, 合并落库(按窗口 delete+insert 幂等)。

    adapter 保留参数与 runner 调用形态一致, 本任务数据源不经 AkShareAdapter。
    返回 {"trade_dates": [...], "rows_written": n,
    "latest": {"trade_date":..., "margin_balance":...} | None};
    数据源不可用时附加 "error" 且 rows_written=0, 不报错。
    """
    try:
        module = _load_margin_module()
        with _akshare_network_env():
            sh = _extract_balances(module.macro_china_market_margin_sh())
            sz = _extract_balances(module.macro_china_market_margin_sz())
    except Exception as exc:  # 数据源不可用: 不报错, 不动旧数据
        logger.warning("margin balance source unavailable: %s", exc)
        return {
            "trade_dates": [],
            "rows_written": 0,
            "latest": None,
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    common = sorted(set(sh) & set(sz))
    if not common:
        return {"trade_dates": [], "rows_written": 0, "latest": None}
    anchor = common[-1]
    cutoff = anchor - timedelta(days=max(int(lookback_days), 1))
    dates = [d for d in common if d >= cutoff]

    rows: list[dict[str, Any]] = []
    for trade_date in dates:
        sse = sh[trade_date]
        szse = sz[trade_date]
        rows.append(
            {
                "trade_date": trade_date,
                "margin_balance": (sse["balance"] or 0.0) + (szse["balance"] or 0.0),
                "sse_balance": sse["balance"],
                "szse_balance": szse["balance"],
                "source": _DEFAULT_SOURCE,
                "raw": {"sse": sse, "szse": szse},
            }
        )
    session.execute(delete(_TABLE).where(_TABLE.c.trade_date.in_(dates)))
    session.execute(insert(_TABLE), rows)

    latest_row = rows[-1]
    return {
        "trade_dates": [d.isoformat() for d in dates],
        "rows_written": len(rows),
        "latest": {
            "trade_date": latest_row["trade_date"].isoformat(),
            "margin_balance": latest_row["margin_balance"],
        },
    }


def latest_margin_balance(session) -> dict[str, Any] | None:
    """最新一行 + 较前一日变化额, 供复盘页统计卡; 空表返回 None。"""
    rows = session.execute(
        select(_TABLE.c.trade_date, _TABLE.c.margin_balance)
        .order_by(_TABLE.c.trade_date.desc())
        .limit(2)
    ).all()
    if not rows:
        return None
    latest_date, latest_balance = rows[0]
    change: float | None = None
    if len(rows) > 1 and latest_balance is not None and rows[1][1] is not None:
        change = float(latest_balance) - float(rows[1][1])
    return {
        "trade_date": latest_date.isoformat() if hasattr(latest_date, "isoformat") else str(latest_date),
        "margin_balance": latest_balance,
        "change": change,
    }
