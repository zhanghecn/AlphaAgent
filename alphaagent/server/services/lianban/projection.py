"""明日推演(同景统计): 找历史上与当日同情绪阶段+同指数年线位置的日子,
统计其次日表现, 给复盘页「🔮 明日推演」卡。

数据源:
- 情绪阶段: mainline_sentiment_history id=1 单行 points JSONB(全历史曲线,
  每日 {date, phase, phase_label, score, temporary, ...}, 升序)。temporary=True
  是盘中投影点, 只可能出现在 API 响应层不进库存行, 这里仍防御性剔除。
- 年线: stock_daily_bars 里 000001.SSE(上证指数)全历史 close, Python 滑动
  窗口算 MA250(含当日的 250 日收盘均值, 市场惯例"年线"; close >= MA250
  即年线上方)。全历史约 7000 行一次查询, 滑动均值 O(n)。
- 次日表现: 指数交易日历(000001.SSE bar 日期序列)的下一交易日, 涨幅用
  close 差分(change_pct 列对指数不落库, 实测为 NULL, 与 review._indices
  同口径回补)。

口径(防未来函数):
- 同景 = 同 phase AND 同 above_ma250; 样本严格早于 trade_date(站在历史日
  复盘时不用该日之后的信息)。
- 样本需有次日指数 bar(历史尾部无次日的剔除); 次日情绪点缺失时样本仍进
  涨幅统计, 只是不进 phase_next / score_change_avg。
- phase_day: points 序列(剔除 temporary 后)向前数连续同 phase 的天数。
- sample_count < MIN_SAMPLES → status="insufficient_data"(统计照常返回);
  当日无情绪点 → 全 None 骨架; 有情绪点但无指数数据/年线未成形 → 阶段字段
  如实回填, 统计 None。两条路径都不炸。

性能: 两次查询(points 单行 JSONB + 指数全历史 close)+ Python 聚合,
盘后功能不进 live 热路径, P95 < 300ms。60s 进程缓存在 API 层
(lianban.py projection_cache)。
"""
from __future__ import annotations

from datetime import date
from statistics import mean, median
from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema as db_schema

SH_INDEX_VT_SYMBOL = "000001.SSE"  # 上证指数(推演锚定指数)
MA_WINDOW = 250  # 年线 = 含当日的 250 日收盘均值
MIN_SAMPLES = 10  # 同景样本下限, 低于此数 status=insufficient_data

_PHASE_LABELS = {
    "ice": "冰点",
    "repair": "修复",
    "divergence": "分歧",
    "climax": "高潮",
    "ebb": "退潮",
}


def empty_projection_payload(trade_date: date | None) -> dict[str, Any]:
    """无数据骨架: 统计全 None, status=insufficient_data(API 无历史点时复用)。"""
    return {
        "trade_date": trade_date.isoformat() if trade_date else None,
        "phase": None,
        "phase_label": None,
        "phase_day": None,
        "above_ma250": None,
        "sample_count": 0,
        "next_day": {"up_prob": None, "avg_change": None, "median_change": None},
        "phase_next": [],
        "score_change_avg": None,
        "scene_dates": [],
        "status": "insufficient_data",
    }


def _phase_label(phase: str | None, fallback: Any = None) -> str | None:
    """point 自带 phase_label 优先, 缺失时按 phase 枚举回填中文。"""
    if fallback:
        return str(fallback)
    return _PHASE_LABELS.get(str(phase)) if phase else None


def _load_points(session) -> list[dict[str, Any]]:
    """mainline_sentiment_history id=1 的 points → 标准化列表(升序)。

    剔除 temporary 盘中投影点与缺 date/phase 的病态行; score 非数值 → None。
    """
    table = db_schema.mainline_sentiment_history
    raw = session.execute(
        select(table.c.points).where(table.c.id == 1)
    ).scalar()
    points: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict) or item.get("temporary"):
            continue
        iso, phase = item.get("date"), item.get("phase")
        if not iso or not phase:
            continue
        try:
            day = date.fromisoformat(str(iso))
        except ValueError:
            continue
        score = item.get("score")
        points.append(
            {
                "date": day,
                "phase": str(phase),
                "phase_label": _phase_label(phase, item.get("phase_label")),
                "score": float(score) if isinstance(score, (int, float)) else None,
            }
        )
    points.sort(key=lambda point: point["date"])
    return points


def _load_index_calendar(session) -> tuple[list[date], dict[date, dict[str, Any]]]:
    """上证全历史 → (交易日序列升序, {date: {"close": c, "above": bool|None}})。

    above: close >= 含当日 MA250 → True(上方); 不足 250 日历史 → None。
    """
    bars = db_schema.stock_daily_bars
    rows = session.execute(
        select(bars.c.trade_date, bars.c.close_price)
        .where(bars.c.vt_symbol == SH_INDEX_VT_SYMBOL)
        .order_by(bars.c.trade_date)
    ).all()
    dates: list[date] = []
    features: dict[date, dict[str, Any]] = {}
    closes: list[float] = []
    window_sum = 0.0
    for row in rows:
        if row.close_price is None:
            continue
        day = row.trade_date
        close = float(row.close_price)
        dates.append(day)
        closes.append(close)
        window_sum += close
        if len(closes) > MA_WINDOW:
            window_sum -= closes[len(closes) - MA_WINDOW - 1]
        above = None
        if len(closes) >= MA_WINDOW:
            above = close >= window_sum / MA_WINDOW
        features[day] = {"close": close, "above": above}
    return dates, features


def _phase_day(points: list[dict[str, Any]], trade_date: date, phase: str) -> int:
    """points 序列向前数连续同 phase 天数(含当日)。"""
    count = 0
    for point in reversed(points):
        if point["date"] > trade_date:
            continue
        if point["phase"] != phase:
            break
        count += 1
    return count


def latest_sentiment_point_date(session) -> date | None:
    """最新有情绪点的日期(API 缺省 date 语义); 无历史 → None。"""
    points = _load_points(session)
    return points[-1]["date"] if points else None


def same_scene_projection(
    session, trade_date: date, *, limit_dates: int = 20
) -> dict[str, Any]:
    """同景推演: 同情绪阶段+同指数年线位置的历史日的次日表现统计。

    返回结构见模块 docstring; status: "ready" | "insufficient_data"。
    """
    points = _load_points(session)
    by_date = {point["date"]: point for point in points}
    current = by_date.get(trade_date)
    payload = empty_projection_payload(trade_date)
    if current is None:
        return payload

    phase = current["phase"]
    payload["phase"] = phase
    payload["phase_label"] = current["phase_label"]
    payload["phase_day"] = _phase_day(points, trade_date, phase)

    calendar, features = _load_index_calendar(session)
    current_feature = features.get(trade_date)
    if current_feature is None or current_feature["above"] is None:
        return payload  # 无指数数据或年线未成形: 阶段字段回填, 统计 None
    above = current_feature["above"]
    payload["above_ma250"] = above

    position = {day: i for i, day in enumerate(calendar)}
    samples: list[dict[str, Any]] = []
    for point in points:
        day = point["date"]
        if day >= trade_date or point["phase"] != phase:
            continue
        feature = features.get(day)
        if (
            feature is None
            or feature["above"] is None
            or feature["above"] != above
        ):
            continue
        index = position[day]
        if index + 1 >= len(calendar):
            continue  # 历史尾部无次日数据, 剔除
        next_day = calendar[index + 1]
        next_change = (features[next_day]["close"] / feature["close"] - 1) * 100
        next_point = by_date.get(next_day)
        score_diff = None
        if (
            next_point is not None
            and point["score"] is not None
            and next_point["score"] is not None
        ):
            score_diff = next_point["score"] - point["score"]
        samples.append(
            {
                "date": day,
                "next_change": next_change,
                "next_phase": next_point["phase"] if next_point else None,
                "next_phase_label": (
                    next_point["phase_label"] if next_point else None
                ),
                "score_diff": score_diff,
            }
        )

    payload["sample_count"] = len(samples)
    if not samples:
        return payload  # status 保持 insufficient_data

    changes = [sample["next_change"] for sample in samples]
    payload["next_day"] = {
        "up_prob": round(sum(1 for change in changes if change > 0) / len(changes), 3),
        "avg_change": round(mean(changes), 2),
        "median_change": round(median(changes), 2),
    }

    buckets: dict[str, dict[str, Any]] = {}
    for sample in samples:
        next_phase = sample["next_phase"]
        if next_phase is None:
            continue
        bucket = buckets.setdefault(
            next_phase,
            {
                "phase": next_phase,
                "label": sample["next_phase_label"],
                "count": 0,
            },
        )
        bucket["count"] += 1
    payload["phase_next"] = [
        {**bucket, "ratio": round(bucket["count"] / len(samples), 2)}
        for bucket in sorted(
            buckets.values(), key=lambda item: (-item["count"], item["phase"])
        )
    ]

    score_diffs = [
        sample["score_diff"] for sample in samples if sample["score_diff"] is not None
    ]
    if score_diffs:
        payload["score_change_avg"] = round(mean(score_diffs), 1)

    payload["scene_dates"] = [
        {
            "date": sample["date"].isoformat(),
            "next_change": round(sample["next_change"], 2),
            "next_phase": sample["next_phase_label"],
        }
        for sample in sorted(samples, key=lambda item: item["date"], reverse=True)[
            : int(limit_dates)
        ]
    ]
    payload["status"] = "ready" if len(samples) >= MIN_SAMPLES else "insufficient_data"
    return payload
