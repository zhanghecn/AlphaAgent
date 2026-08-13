"""Stateless realtime ranking for the 潜龙首板 board."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.services.a_share_universe import is_eligible_main_board


LEADER_LIMIT = 100
SHANGHAI = ZoneInfo("Asia/Shanghai")


def get_live_first_board() -> dict[str, object]:
    """Build one realtime first-board ranking from the current limit-up pool."""

    now = datetime.now(SHANGHAI)
    try:
        pools = AkShareAdapter().limit_up_pools()
    except Exception as exc:  # noqa: BLE001
        return _unavailable_payload(now, f"涨停池暂时不可用：{exc.__class__.__name__}")
    return build_live_first_board_payload(pools, now=now)


def build_live_first_board_payload(
    pools_payload: Mapping[str, object],
    *,
    now: datetime,
) -> dict[str, object]:
    """Filter the live pool to non-ST main-board first boards and rank them."""

    pools = pools_payload.get("pools")
    pools = pools if isinstance(pools, Mapping) else {}
    zt_pool = pools.get("zt")
    zt_pool = zt_pool if isinstance(zt_pool, Mapping) else {}
    raw_items = zt_pool.get("items")
    raw_items = raw_items if isinstance(raw_items, list) else []
    if str(zt_pool.get("status") or "") == "unavailable":
        return _unavailable_payload(now, "涨停池暂时不可用")

    leaders = [
        leader
        for item in raw_items
        if isinstance(item, Mapping)
        and (leader := _first_board_leader(item)) is not None
    ]
    leaders.sort(key=_live_strength_sort_key)
    for rank, leader in enumerate(leaders, start=1):
        leader["rank"] = rank

    return {
        "status": "ok",
        "trade_date": _trade_date(pools_payload.get("trade_date"), now.date()),
        "captured_at": str(pools_payload.get("updated_at") or now.isoformat()),
        "session_stage": _session_stage(now),
        "source": str(pools_payload.get("source") or "akshare.stock_ztb_em"),
        "data_quality": {
            "status": "ready",
            "is_stale": False,
            "pool_total": _integer(zt_pool.get("total")) or len(raw_items),
            "first_board_total": len(leaders),
        },
        "leaders": leaders[:LEADER_LIMIT],
    }


def _first_board_leader(item: Mapping[str, object]) -> dict[str, object] | None:
    vt_symbol = str(item.get("vt_symbol") or "").upper()
    name = str(item.get("name") or "")
    if _integer(item.get("limit_up_count")) != 1:
        return None
    if not is_eligible_main_board(vt_symbol, name):
        return None

    raw = item.get("raw")
    raw = raw if isinstance(raw, Mapping) else {}
    seal_amount = _number(item.get("limit_amount"))
    turnover = _first_number(raw, "成交额", "成交金额", "成交额(元)", "amount")
    return {
        "vt_symbol": vt_symbol,
        "name": name,
        "last_price": _number(item.get("close_price")),
        "limit_price": _number(item.get("limit_up_price")),
        "change_pct": _number(item.get("change_pct")),
        "seal_amount": seal_amount,
        "turnover_rate": _number(item.get("turnover_rate")),
        "volume_ratio": _number(item.get("volume_ratio")),
        "first_limit_time": _time_text(item.get("first_limit_time")),
        "last_limit_time": _time_text(item.get("last_limit_time")),
        "open_times": _integer(
            raw.get("开板次数") or raw.get("炸板次数") or raw.get("开板次数(次)")
        ),
        "seal_to_turnover_ratio": (
            round(seal_amount / turnover, 6)
            if seal_amount is not None and turnover is not None and turnover > 0
            else None
        ),
    }


def _live_strength_sort_key(item: Mapping[str, object]) -> tuple[float, str, int, float, str]:
    ratio = _number(item.get("seal_to_turnover_ratio"))
    first_limit_time = str(item.get("first_limit_time") or "99:99:99")
    open_times = _integer(item.get("open_times"))
    seal_amount = _number(item.get("seal_amount"))
    return (
        -(ratio if ratio is not None else -1.0),
        first_limit_time,
        open_times if open_times is not None else 999,
        -(seal_amount if seal_amount is not None else 0.0),
        str(item.get("vt_symbol") or ""),
    )


def _unavailable_payload(now: datetime, message: str) -> dict[str, object]:
    return {
        "status": "unavailable",
        "trade_date": now.date().isoformat(),
        "captured_at": now.isoformat(timespec="seconds"),
        "session_stage": _session_stage(now),
        "source": "akshare.stock_ztb_em",
        "data_quality": {
            "status": "unavailable",
            "is_stale": True,
            "pool_total": 0,
            "first_board_total": 0,
            "message": message,
        },
        "leaders": [],
    }


def _trade_date(value: object, fallback: date) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return fallback.isoformat()


def _session_stage(now: datetime) -> str:
    current = now.timetz().replace(tzinfo=None)
    if current < time(9, 30):
        return "preopen"
    if current <= time(11, 30):
        return "morning"
    if current < time(13, 0):
        return "lunch"
    if current <= time(15, 0):
        return "afternoon"
    return "closed"


def _first_number(values: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        number = _number(values.get(key))
        if number is not None:
            return number
    return None


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _time_text(value: object) -> str | None:
    text = str(value or "").strip()
    if text.isdigit():
        text = text.zfill(6)
        if len(text) == 6:
            return f"{text[:2]}:{text[2:4]}:{text[4:]}"
    return text or None
