"""大盘择时面板数据 service(进程内缓存)。

为前端「大盘分析」页提供全套数据: 概览 + 上证 K 线 + 信号事件 + 准确率矩阵。
全量计算一次(约 1 分钟, 含全市场广度), 进程内缓存 30 分钟, 后续请求秒回。
并发请求用锁避免重复计算。
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update

from alphaagent.market.providers import RealMarketDataClient, _CHINA_TZ, _china_today, _is_intraday_china
from alphaagent.server.services.quant.market_context import compute_market_contexts
from alphaagent.server.services.quant.market_timing import backtest as bt
from alphaagent.server.services.quant.market_timing import factors as fac
from alphaagent.server.services.quant.market_timing import series as ser
from alphaagent.server.services.quant.market_timing import signal as sig

PANEL_START = date(2024, 5, 28)  # 指数数据起点
LIVE_OVERLAY_END = dt_time(19, 30)  # 覆盖 19:00 盘后日线同步启动和短暂执行时间


def _cache_ttl() -> int:
    """内存缓存 TTL: 盘中 5min(实时预警新鲜), 盘后 30min(日线一天一变)。"""
    return 300 if _is_intraday_china() else 1800


PANEL_FRESH_HOURS = 24  # 库内 panel 24h 内视为新鲜(日线数据一天一变)
INDEX_FOR_CHART = "000001.SSE"  # 前端主图用上证指数(主人最熟悉)
PHASE_LABELS = {
    "uptrend": "主升",
    "warming": "回暖",
    "rotation": "震荡",
    "retreat": "退潮",
    "unknown": "未知",
}

_cache: dict[str, Any] = {"panel": None, "ts": 0.0}
_lock = threading.Lock()


def _load_panel_row(session: Any, schema: Any) -> Any:
    """读库内最新预计算面板(单行 id=1)。"""
    if not hasattr(schema, "market_timing_panel"):
        return None
    return session.execute(
        select(schema.market_timing_panel.c.panel, schema.market_timing_panel.c.computed_at)
        .where(schema.market_timing_panel.c.id == 1)
    ).first()


def _is_panel_fresh(computed_at: Any) -> bool:
    if computed_at is None:
        return False
    now = datetime.now(computed_at.tzinfo) if getattr(computed_at, "tzinfo", None) else datetime.utcnow()
    return (now - computed_at) < timedelta(hours=PANEL_FRESH_HOURS)


def _save_panel_row(session: Any, schema: Any, panel: dict) -> None:
    """把预计算面板 upsert 到 market_timing_panel(id=1)。"""
    if not hasattr(schema, "market_timing_panel"):
        return
    tbl = schema.market_timing_panel
    exists = session.execute(select(tbl.c.id).where(tbl.c.id == 1)).first()
    if exists:
        session.execute(update(tbl).where(tbl.c.id == 1).values(panel=panel, computed_at=func.now()))
    else:
        session.execute(insert(tbl).values(id=1, panel=panel))
    session.commit()


def _load_index_ohlcv(session: Any, schema: Any, vt_symbol: str, start: date, end: date) -> list[dict]:
    table = schema.stock_daily_bars
    rows = session.execute(
        select(
            table.c.trade_date,
            table.c.open_price,
            table.c.high_price,
            table.c.low_price,
            table.c.close_price,
            table.c.volume,
            table.c.turnover,
        )
        .where(table.c.vt_symbol == vt_symbol)
        .where(table.c.trade_date >= start)
        .where(table.c.trade_date <= end)
        .order_by(table.c.trade_date)
    ).all()
    return [
        {
            "date": str(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5] or 0),
            "turnover": float(r[6] or 0),
        }
        for r in rows
    ]


def _is_live_today_overlay_window(now: datetime | None = None) -> bool:
    """是否允许用实时快照补今天主图。

    交易时段内用于实时预警; 15:00 后到日线同步前用于避免页面退回昨天。
    """
    now = now or datetime.now(_CHINA_TZ)
    if _is_intraday_china(now):
        return True
    if now.weekday() >= 5:
        return False
    current = now.time()
    return dt_time(15, 0) <= current < LIVE_OVERLAY_END


def _live_index_bar_for_today() -> dict | None:
    try:
        detail = RealMarketDataClient().index_detail("000001", "SSE") or {}
    except Exception:  # noqa: BLE001  实时源不可用则退回基础 panel
        return None

    last_price = _to_float(detail.get("last_price"))
    volume = _to_float(detail.get("volume"))
    if not last_price or not volume or volume <= 0:
        return None

    return {
        "date": _china_today().isoformat(),
        "open": _to_float(detail.get("open_price")) or last_price,
        "close": last_price,
        "high": _to_float(detail.get("high_price")) or last_price,
        "low": _to_float(detail.get("low_price")) or last_price,
        "volume": volume,
        "turnover": _to_float(detail.get("turnover")) or _to_float(detail.get("amount")) or 0.0,
    }


def _upsert_latest_bar(bars: list[dict], latest_bar: dict | None) -> list[dict]:
    if latest_bar is None:
        return bars
    updated = list(bars)
    latest_date = latest_bar.get("date")
    if updated and updated[-1].get("date") == latest_date:
        updated[-1] = latest_bar
    else:
        updated.append(latest_bar)
    return updated


def _carry_context_to_date(context: Any, target_date: date) -> Any:
    """复用滞后市场广度时保留数值，但把因子归属到目标交易日。"""
    return replace(context, trade_date=target_date)


def _build_timing_series(
    factors: list[Any],
    events: list[Any],
    closes: list[float] | None = None,
    up_ratios: list[float | None] | None = None,
) -> list[dict]:
    """构建逐日合力和候选事件序列，供日期表与审计共用。"""
    event_by_date = {event.trade_date: event for event in events}
    rows: list[dict] = []
    aligned_closes = closes if closes is not None and len(closes) == len(factors) else None
    aligned_up_ratios = (
        up_ratios
        if aligned_closes is not None
        and up_ratios is not None
        and len(up_ratios) == len(factors)
        else None
    )
    danger_states = sig.build_danger_states(
        factors,
        aligned_closes,
        aligned_up_ratios,
    )
    active_directions = sig.build_active_directions(
        [factor.trade_date for factor in factors],
        events,
    )
    for index, factor in enumerate(factors):
        event = event_by_date.get(factor.trade_date)
        reversal_gold = (
            aligned_closes is not None
            and sig.is_reversal_gold(aligned_closes, index)
        )
        structural_breakdown = bool(
            aligned_closes is not None
            and aligned_up_ratios is not None
            and sig.is_structural_breakdown(
                factor,
                aligned_closes,
                index,
                aligned_up_ratios[index],
            )
        )
        zone_direction, _ = sig.candidate_setup(
            factor,
            reversal_gold=reversal_gold,
            structural_breakdown=structural_breakdown,
        )
        rows.append(
            {
                "date": str(factor.trade_date),
                "bull_force": factor.bull_force,
                "bear_force": factor.bear_force,
                "active_direction": active_directions[index],
                "zone_direction": zone_direction or "NEUTRAL",
                "danger_state": danger_states[index],
                "phase": factor.phase,
                "event": (
                    {
                        "direction": event.direction,
                        "status": event.status,
                        "grade": event.grade,
                        "setup_type": event.setup_type,
                        "confirm_date": (
                            str(event.confirm_date) if event.confirm_date else None
                        ),
                    }
                    if event is not None
                    else None
                ),
            }
        )
    return rows


def _build_overview(
    latest: Any,
    latest_signal: Any,
    index_bars: list[dict],
    current_direction: str,
    danger_state: str = sig.NORMAL,
) -> dict:
    if latest is None:
        return {}
    idx_close = index_bars[-1]["close"] if index_bars else None
    idx_prev = index_bars[-2]["close"] if len(index_bars) >= 2 else None
    idx_chg = ((idx_close / idx_prev - 1) * 100) if idx_close and idx_prev else None
    factor_date = str(latest.trade_date)
    quote_date = str(index_bars[-1]["date"]) if index_bars else factor_date
    return {
        "latest_date": factor_date,
        "factor_date": factor_date,
        "quote_date": quote_date,
        "current_direction": current_direction,
        "danger_state": danger_state,
        "phase": latest.phase,
        "phase_label": PHASE_LABELS.get(latest.phase, latest.phase),
        "bull_force": latest.bull_force,
        "bear_force": latest.bear_force,
        "factors": {
            "trend": latest.trend,
            "momentum": latest.momentum,
            "breadth": latest.breadth,
            "structure": latest.structure,
            "volume": latest.volume,
        },
        "top_factors": {
            "macd_top": latest.macd_top,
            "breadth_top": latest.breadth_top,
            "mom_5d": latest.mom_5d,
            "mom_20d": latest.mom_20d,
            "above_ma20": latest.close_above_ma20,
            "market_score": latest.evidence.get("market_score"),
            "risk_score": latest.evidence.get("risk_score"),
            "rsi": latest.evidence.get("rsi"),
            "macd_hist": latest.evidence.get("macd_hist"),
            "vol_pct": latest.evidence.get("vol_pct"),
            "volume_ratio": latest.evidence.get("volume_ratio"),
            "vol_price_div": latest.evidence.get("vol_price_div"),
            "trend_breakdown": latest.evidence.get("trend_breakdown"),
            "regime": latest.evidence.get("regime"),
        },
        "index_close": idx_close,
        "index_change_pct": round(idx_chg, 2) if idx_chg is not None else None,
        "latest_signal": (
            {
                "direction": latest_signal.direction,
                "status": latest_signal.status,
                "grade": latest_signal.grade,
                "setup_type": latest_signal.setup_type,
                "date": str(latest_signal.trade_date),
                "confirm_date": (
                    str(latest_signal.confirm_date) if latest_signal.confirm_date else None
                ),
                "bull_force": latest_signal.bull_force,
                "bear_force": latest_signal.bear_force,
            }
            if latest_signal
            else None
        ),
    }


def _build_chart(index_bars: list[dict], comp: list, events: list) -> dict:
    return {
        "index_symbol": INDEX_FOR_CHART,
        "bars": index_bars,
        "composite": [{"date": str(b.trade_date), "close": b.close} for b in comp],
        "signals": [
            {
                "date": str(e.trade_date),
                "direction": e.direction,
                "status": e.status,
                "grade": e.grade,
                "setup_type": e.setup_type,
                "confirm_date": str(e.confirm_date) if e.confirm_date else None,
                "bull_force": e.bull_force,
                "bear_force": e.bear_force,
                "phase": e.phase,
                "reasons": e.reasons,
            }
            for e in events
        ],
    }


def _serialize_accuracy_buckets(buckets: list[Any]) -> list[dict]:
    return [
        {
            "direction": bucket.direction,
            "grade": bucket.grade,
            "horizon": bucket.horizon,
            "count": bucket.count,
            "win_rate": round(bucket.win_rate, 4),
            "avg_return": round(bucket.avg_return, 4),
            "worst_return": round(bucket.worst_return, 4),
            "ci_low": round(bucket.ci_low, 4),
            "ci_high": round(bucket.ci_high, 4),
        }
        for bucket in buckets
    ]


def _serialize_accuracy_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "date": str(row["date"]),
            "candidate_date": str(row["candidate_date"]),
            "confirm_date": str(row["confirm_date"]) if row["confirm_date"] else None,
            "start_date": str(row["start_date"]),
            "direction": row["direction"],
            "setup_type": row["setup_type"],
            "status": row["status"],
            "grade": row["grade"],
            "horizon": row["horizon"],
            "return": round(row["return"], 4),
            "correct": row["correct"],
        }
        for row in rows
    ]


def _build_accuracy(acc: dict) -> dict:
    return {
        "buckets": _serialize_accuracy_buckets(acc["buckets"]),
        "rows": _serialize_accuracy_rows(acc["rows"]),
        "candidate_buckets": _serialize_accuracy_buckets(acc["candidate_buckets"]),
        "candidate_rows": _serialize_accuracy_rows(acc["candidate_rows"]),
        "evaluation_basis": acc["evaluation_basis"],
        "random_baseline": {str(k): round(v, 4) for k, v in acc["random_baseline_up_rate"].items()},
        "buy_hold_return_pct": (
            round(acc["buy_hold_return_pct"], 2) if acc["buy_hold_return_pct"] is not None else None
        ),
        "n_events": acc["n_events"],
        "n_confirmed": acc.get("n_confirmed", 0),
        "n_invalidated": acc.get("n_invalidated", 0),
        "n_pending": acc.get("n_pending", 0),
        "invalidated_summary": acc.get("invalidated_summary") or {},
        "silver_caveat": (
            "当前样本整体偏牛且缺乏完整熊市与大顶阶段，"
            "银手指表现仅供参考，需更长历史数据验证"
        ),
    }


def _compute_panel(session: Any, schema: Any) -> dict:
    last = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.vt_symbol == INDEX_FOR_CHART)
        .order_by(schema.stock_daily_bars.c.trade_date.desc())
        .limit(1)
    ).scalar_one()
    end = last if isinstance(last, date) else PANEL_START

    comp = ser.load_composite_series(session, schema, PANEL_START, end)
    if not comp:
        return {"empty": True}
    # 盘中: DB 还没今天日线时, 追加七大指数实时合成的今天 bar(实时预警)
    today = _china_today()
    live_index_bar = None
    if isinstance(last, date) and last < today:
        today_bar = ser.intraday_today_bar(comp[-1].close, comp[-1].turnover)
        if today_bar is not None:
            live_index_bar = _live_index_bar_for_today()
            if live_index_bar is not None:
                comp = comp + [today_bar]
    dates = [b.trade_date for b in comp]
    ctx_map = compute_market_contexts(session, schema, dates)
    ctx_list = [ctx_map.get(d) for d in dates]
    # 盘中今天 ctx 用昨天近似(广度滞后, 够预警; trend/momentum/structure/volume 仍用今天实时 close)
    if len(ctx_list) >= 2 and ctx_list[-1] is None and ctx_list[-2] is not None:
        ctx_list[-1] = _carry_context_to_date(ctx_list[-2], dates[-1])
    closes = [b.close for b in comp]
    turns = [b.turnover for b in comp]
    factor_seq = []
    factor_bars = []
    for i in range(len(dates)):
        if ctx_list[i] is None:
            continue
        ctx_window = [c for c in ctx_list[: i + 1] if c is not None]
        factor_seq.append(fac.compute_factors(ctx_window, closes[: i + 1], turns[: i + 1]))
        factor_bars.append(comp[i])

    factor_closes = [bar.close for bar in factor_bars]
    factor_up_ratios = [bar.up_ratio for bar in factor_bars]

    events = sig.detect_events(
        factor_seq,
        factor_closes,
        factor_up_ratios,
        confirmed_through=end if live_index_bar is not None else None,
    )
    accuracy = bt.evaluate(events, factor_bars)
    index_bars = _upsert_latest_bar(
        _load_index_ohlcv(session, schema, INDEX_FOR_CHART, PANEL_START, end),
        live_index_bar,
    )

    latest = factor_seq[-1] if factor_seq else None
    latest_signal = next(
        (e for e in reversed(events) if e.status == sig.STATUS_CONFIRMED), None
    ) if events else None
    timing_series = _build_timing_series(
        factor_seq,
        events,
        factor_closes,
        factor_up_ratios,
    )
    latest_danger_state = (
        timing_series[-1]["danger_state"]
        if timing_series
        else sig.NORMAL
    )
    current_direction = (
        timing_series[-1]["active_direction"]
        if timing_series
        else "NEUTRAL"
    )

    return {
        "overview": _build_overview(
            latest,
            latest_signal,
            index_bars,
            current_direction,
            latest_danger_state,
        ),
        "chart": _build_chart(index_bars, comp, events),
        "timing_series": timing_series,
        "accuracy": _build_accuracy(accuracy),
        "generated_at": int(time.time()),
        "sample_range": [str(comp[0].trade_date), str(comp[-1].trade_date)],
    }


def _base_panel(session: Any, schema: Any, force_refresh: bool = False) -> dict:
    """基础面板(三层缓存: 内存 30min → 库 24h → 现算+落库), 不含盘中实时 overlay。
    内存命中 <1ms; 库命中 <100ms; 现算+落库 ~16s(仅首次/过期/force)。"""
    now = time.time()
    if not force_refresh and _cache["panel"] and now - _cache["ts"] < _cache_ttl():
        return _cache["panel"]
    with _lock:
        if not force_refresh and _cache["panel"] and time.time() - _cache["ts"] < _cache_ttl():
            return _cache["panel"]
        # 库内 panel 新鲜则直接读(避免现算)
        if not force_refresh:
            row = _load_panel_row(session, schema)
            if row and _is_panel_fresh(row.computed_at):
                panel = row.panel
                _cache["panel"] = panel
                _cache["ts"] = time.time()
                return panel
        # 现算 + 落库
        panel = _compute_panel(session, schema)
        _save_panel_row(session, schema, panel)
        _cache["panel"] = panel
        _cache["ts"] = time.time()
    return panel


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _overlay_intraday(panel: dict) -> dict:
    """用今天实时指数 overlay: chart 最新K线 + overview 点位/涨跌。

    交易时段用于实时预警; 盘后日线同步前用于避免页面主图停在昨天。
    因子/信号保持基础 panel; 不落库。
    """
    if panel.get("empty") or not _is_live_today_overlay_window():
        return panel
    panel = dict(panel)  # 顶层浅 copy, 避免污染内存缓存里的 base panel
    today_bar = _live_index_bar_for_today()
    if today_bar is None:
        return panel
    chart = dict(panel.get("chart") or {})
    bars = _upsert_latest_bar(list(chart.get("bars") or []), today_bar)
    panel["chart"] = {**chart, "bars": bars}
    ov = dict(panel.get("overview") or {})
    ov["index_close"] = today_bar["close"]
    if len(bars) >= 2:
        prev_close = _to_float(bars[-2].get("close"))
        if prev_close:
            ov["index_change_pct"] = round((today_bar["close"] / prev_close - 1) * 100, 2)
    ov["quote_date"] = today_bar["date"]
    ov["is_intraday"] = _is_intraday_china()
    ov["is_live_snapshot"] = True
    panel["overview"] = ov
    return panel


def get_market_timing_panel(session: Any, schema: Any, force_refresh: bool = False) -> dict:
    """获取大盘择时面板(基础面板 + 盘中实时 overlay)。

    基础面板三层缓存(内存/库/现算), 含昨日收盘的因子与信号;
    盘中交易时段再 overlay 今天实时点位到 chart 最新K线 + overview。
    """
    return _overlay_intraday(_base_panel(session, schema, force_refresh))


def start_intraday_refresher() -> None:
    """启动后台 daemon thread: 盘中每 5min force_refresh panel。

    保证主人访问 /market 读到的缓存 ≤5min 新鲜(含今天实时候选)。
    非交易时段空转 sleep; 失败静默(下次 5min 重试), 不影响主服务。
    在 main.py lifespan 启动一次即可。
    """
    def _loop() -> None:
        # 函数内 import 避免模块加载期循环依赖
        from alphaagent.server.db import schema as _schema
        from alphaagent.server.db.session import session_scope

        while True:
            try:
                if _is_intraday_china():
                    with session_scope() as session:
                        get_market_timing_panel(session, _schema, force_refresh=True)
            except Exception:  # noqa: BLE001  后台任务不能挂
                pass
            time.sleep(300)

    threading.Thread(target=_loop, daemon=True, name="intraday-mt-refresh").start()
