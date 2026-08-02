"""First-board leader strength tracker (read-only view over the live snapshot).

盘中实时跟踪首板强度 + Phase 0 白名单因子潜力分：

- **潜力分**（v2）：Phase 0 稳定性门白名单因子的横截面分位加权
  （concept_max_return_20d 0.30 / volume_ratio_5_60 0.15 / strength 族合计 0.40
  上限内 drawdown_126d 0.15 + position_126d 0.10 + prior_return_20d 0.08
  + prior_return_5d 0.07），缺字段权重重分配；因子全部 D-1 可观测。
- **封板质量分**（0.15）：实时封单比分位（封板瞬间可观测，非未来函数）；
  封单保持率 < 0.7 标记撤单预警并扣分。未封板候选权重重分配给 D-1 因子。
- **尾盘降权**：14:00 后封板 D+1 溢价最差（wave 研究 +0.66%/胜率 53.7%），
  标记 ``late_seal`` 且潜力分减半。
- **市场温度指示**：昨日全市场首板数（stock_events 滞后口径，展示用——
  Phase 0 判定滞后温度未过稳定性门，不做硬门不进打分）。

只读现有 10 秒实时快照（``get_latest_live_snapshot``）+ stock_events 温度查询，
绝不新建扫描、不改 snapshot 构建。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.live_service import get_latest_live_snapshot
from sqlalchemy import select

LEADER_LIMIT = 20
LATE_SEAL_TIME = "14:00:00"
SEAL_RETENTION_WARN = 0.7
# 温度分档（wave 研究分位：≤32 冰点出龙 / ≥69 涨停潮稀释；展示用不做硬门）
TEMP_COLD_MAX = 32
TEMP_HOT_MIN = 69

# Phase 0 白名单权重（族上限：strength 族合计 0.40、单因子 ≤0.25；合计 0.85，
# 剩余 0.15 为封板质量分，未封板时重分配给 D-1 因子）
_FACTOR_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("concept_max_return_20d", 0.30),
    ("volume_ratio_5_60", 0.15),
    ("drawdown_from_126d_high_pct", 0.15),
    ("position_126d", 0.10),
    ("prior_return_20d_pct", 0.08),
    ("prior_return_5d_pct", 0.07),
)
_SEAL_WEIGHT = 0.15
_SEAL_WEAKENING_PENALTY = 0.05

_TEMPERATURE_CACHE_SECONDS = 60
_temperature_cache: dict[str, object] = {"at": None, "value": None}


def build_first_board_leader_snapshot() -> dict[str, object]:
    """读取最新实时快照并返回潜龙首板强度榜。"""

    return select_first_board_leaders(get_latest_live_snapshot())


def select_first_board_leaders(
    snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    """从实时快照过滤 first_board + 潜力分排序，返回 top ``LEADER_LIMIT``。"""

    if not snapshot:
        return _empty_leader_snapshot()
    recommendations = snapshot.get("recommendations") or {}
    lanes = (recommendations.get("lanes") or {}) if isinstance(recommendations, Mapping) else {}
    now_signals = lanes.get("now") or []
    first_boards = [
        dict(signal)
        for signal in now_signals
        if str(signal.get("board_lane") or "") == "first_board"
    ]
    _attach_potential_scores(first_boards)
    first_boards.sort(
        key=lambda signal: (
            _num(signal.get("potential_score")) or 0.0,
            *_leader_strength_key(signal),
        ),
        reverse=True,
    )
    return {
        "trade_date": snapshot.get("trade_date"),
        "captured_at": snapshot.get("captured_at"),
        "session_stage": snapshot.get("session_stage"),
        "mode": snapshot.get("mode"),
        "data_quality": snapshot.get("data_quality") or {},
        "market_temperature": _market_temperature(snapshot.get("trade_date")),
        "leaders": first_boards[:LEADER_LIMIT],
    }


def _attach_potential_scores(signals: list[dict[str, object]]) -> None:
    """横截面分位加权潜力分 + 封板质量 + 尾盘降权（就地写入）。"""

    percentiles: dict[str, dict[str, float]] = {}
    for factor_key, _weight in _FACTOR_WEIGHTS:
        percentiles[factor_key] = _cross_section_percentiles(signals, factor_key)
    seal_percentiles = _cross_section_percentiles(signals, "seal_to_turnover_ratio")
    for signal in signals:
        available: list[tuple[str, float, float]] = []  # (factor, weight, percentile)
        for factor_key, weight in _FACTOR_WEIGHTS:
            percentile = percentiles[factor_key].get(str(signal.get("vt_symbol") or ""))
            if percentile is not None:
                available.append((factor_key, weight, percentile))
        symbol = str(signal.get("vt_symbol") or "")
        seal_percentile = seal_percentiles.get(symbol)
        retention = _num(signal.get("seal_amount_retention_ratio"))
        seal_weakening = retention is not None and retention < SEAL_RETENTION_WARN
        if seal_percentile is not None:
            available.append(("seal_to_turnover_ratio", _SEAL_WEIGHT, seal_percentile))
        total_weight = sum(weight for _, weight, _ in available)
        score = (
            sum(weight * percentile for _, weight, percentile in available) / total_weight
            if total_weight > 0
            else 0.0
        )
        if seal_weakening:
            score = max(0.0, score - _SEAL_WEAKENING_PENALTY)
        first_limit_time = str(signal.get("first_limit_time") or "")
        late_seal = bool(first_limit_time and first_limit_time >= LATE_SEAL_TIME)
        if late_seal:
            score *= 0.5
        signal["potential_score"] = round(score, 4)
        signal["factor_percentiles"] = {
            factor: round(percentile, 4) for factor, _, percentile in available
        }
        signal["seal_weakening"] = seal_weakening
        signal["late_seal"] = late_seal


def _cross_section_percentiles(
    signals: list[dict[str, object]], factor_key: str
) -> dict[str, float]:
    """因子在当日首板候选中的横截面分位（0..1，越大越好；方向均为 higher）。

    同值取平均秩（ties 不分先后）；唯一候选给满分。
    """

    valued = sorted(
        (
            (value, str(signal.get("vt_symbol") or ""))
            for signal in signals
            if (value := _num(signal.get(factor_key))) is not None
        ),
        key=lambda item: item[0],
    )
    total = len(valued)
    if not total:
        return {}
    if total == 1:
        return {valued[0][1]: 1.0}
    percentiles: dict[str, float] = {}
    index = 0
    while index < total:
        end = index
        while end + 1 < total and valued[end + 1][0] == valued[index][0]:
            end += 1
        percentile = round(((index + end) / 2) / (total - 1), 6)
        for position in range(index, end + 1):
            percentiles[valued[position][1]] = percentile
        index = end + 1
    return percentiles


def _market_temperature(trade_date: object) -> dict[str, object]:
    """昨日全市场首板数（滞后口径，展示用）+ 冷/温/热分档。"""

    today = _as_date(trade_date) or datetime.now(
        timezone(timedelta(hours=8))
    ).date()
    cache_at = _temperature_cache.get("at")
    cache_value = _temperature_cache.get("value")
    if (
        isinstance(cache_at, datetime)
        and isinstance(cache_value, Mapping)
        and cache_value.get("trade_date") == today.isoformat()
        and (datetime.now(timezone.utc) - cache_at).total_seconds()
        < _TEMPERATURE_CACHE_SECONDS
    ):
        return dict(cache_value)
    result = _load_market_temperature(today)
    _temperature_cache["at"] = datetime.now(timezone.utc)
    _temperature_cache["value"] = result
    return result


def _load_market_temperature(today: date) -> dict[str, object]:
    # 只查最近 10 个日历日（event_date 历史上 %Y%m%d 与 ISO 两种格式并存）
    candidate_days: dict[str, str] = {}  # event_date 原格式 -> 归一化 ISO
    for offset in range(1, 11):
        day = today - timedelta(days=offset)
        candidate_days[day.strftime("%Y%m%d")] = day.isoformat()
        candidate_days[day.isoformat()] = day.isoformat()
    try:
        with session_scope() as session:
            rows = session.execute(
                select(
                    schema.stock_events.c.event_date,
                    schema.stock_events.c.raw,
                ).where(
                    (schema.stock_events.c.source == "akshare.stock_ztb_em")
                    & (schema.stock_events.c.event_type == "limit_pool_zt")
                    & (schema.stock_events.c.event_date.in_(list(candidate_days)))
                )
            ).all()
    except Exception:  # noqa: BLE001
        return {"trade_date": today.isoformat(), "available": False}
    by_date: dict[str, int] = {}
    for event_date, raw in rows:
        day = candidate_days.get(str(event_date or ""))
        if day is None:
            continue
        limit_times = _num((raw or {}).get("连板数")) if isinstance(raw, Mapping) else None
        if limit_times == 1:
            by_date[day] = by_date.get(day, 0) + 1
    if not by_date:
        return {"trade_date": today.isoformat(), "available": False}
    latest_day = max(by_date)
    count = by_date[latest_day]
    level = "cold" if count <= TEMP_COLD_MAX else ("hot" if count >= TEMP_HOT_MIN else "neutral")
    return {
        "trade_date": today.isoformat(),
        "available": True,
        "lag1_trade_date": latest_day,
        "lag1_first_board_count": count,
        "level": level,
        "note": "滞后温度仅展示：Phase 0 判定未过稳定性门（逐月一致性不足），不做硬门不进打分",
    }


def _empty_leader_snapshot() -> dict[str, object]:
    return {
        "trade_date": None,
        "captured_at": None,
        "session_stage": None,
        "mode": None,
        "data_quality": {},
        "market_temperature": {"available": False},
        "leaders": [],
    }


def _leader_strength_key(signal: Mapping[str, object]) -> tuple[float, float, float, float]:
    """强度排序：涨幅高 > 距板近 > 概念龙前 > 封单大。"""

    change = _num(signal.get("change_pct")) or 0.0
    distance = _num(signal.get("distance_to_limit_pct"))
    seal = _num(signal.get("seal_amount")) or 0.0
    concept_rank = _num(signal.get("concept_leader_rank"))
    return (
        change,
        -(distance if distance is not None else 999.0),
        -(concept_rank if concept_rank is not None else 9999.0),
        seal,
    )


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _num(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
