"""大盘择时面板数据 service(进程内缓存)。

为前端「大盘分析」页提供全套数据: 概览 + 上证 K 线 + 信号事件 + 准确率矩阵。
全量计算一次(约 1 分钟, 含全市场广度), 进程内缓存 30 分钟, 后续请求秒回。
并发请求用锁避免重复计算。
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update

from alphaagent.market.providers import RealMarketDataClient, _china_today, _is_intraday_china
from alphaagent.server.services.quant.market_context import compute_market_contexts
from alphaagent.server.services.quant.market_timing import backtest as bt
from alphaagent.server.services.quant.market_timing import factors as fac
from alphaagent.server.services.quant.market_timing import series as ser
from alphaagent.server.services.quant.market_timing import signal as sig

PANEL_START = date(2024, 5, 28)  # 指数数据起点
_CACHE_TTL = 1800  # 内存缓存 30 分钟
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


def _build_overview(latest: Any, latest_signal: Any, index_bars: list[dict]) -> dict:
    if latest is None:
        return {}
    idx_close = index_bars[-1]["close"] if index_bars else None
    idx_prev = index_bars[-2]["close"] if len(index_bars) >= 2 else None
    idx_chg = ((idx_close / idx_prev - 1) * 100) if idx_close and idx_prev else None
    return {
        "latest_date": str(latest.trade_date),
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
                "grade": latest_signal.grade,
                "date": str(latest_signal.trade_date),
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
                "grade": e.grade,
                "bull_force": e.bull_force,
                "bear_force": e.bear_force,
                "phase": e.phase,
                "reasons": e.reasons,
            }
            for e in events
        ],
    }


def _build_accuracy(acc: dict) -> dict:
    return {
        "buckets": [
            {
                "direction": b.direction,
                "grade": b.grade,
                "horizon": b.horizon,
                "count": b.count,
                "win_rate": round(b.win_rate, 4),
                "avg_return": round(b.avg_return, 4),
                "worst_return": round(b.worst_return, 4),
                "ci_low": round(b.ci_low, 4),
                "ci_high": round(b.ci_high, 4),
            }
            for b in acc["buckets"]
        ],
        "random_baseline": {str(k): round(v, 4) for k, v in acc["random_baseline_up_rate"].items()},
        "buy_hold_return_pct": (
            round(acc["buy_hold_return_pct"], 2) if acc["buy_hold_return_pct"] is not None else None
        ),
        "n_events": acc["n_events"],
        "silver_caveat": (
            "样本期(2024-05~2026-06)为单边牛市(+71%), 缺乏真正顶部, "
            "银手指准确率仅供参考, 需更长含熊市数据验证"
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
    dates = [b.trade_date for b in comp]
    ctx_map = compute_market_contexts(session, schema, dates)
    ctx_list = [ctx_map.get(d) for d in dates]
    closes = [b.close for b in comp]
    turns = [b.turnover for b in comp]
    factor_seq = []
    for i in range(len(dates)):
        if ctx_list[i] is None:
            continue
        ctx_window = [c for c in ctx_list[: i + 1] if c is not None]
        factor_seq.append(fac.compute_factors(ctx_window, closes[: i + 1], turns[: i + 1]))

    events = sig.detect_events(factor_seq)
    accuracy = bt.evaluate(events, comp)
    index_bars = _load_index_ohlcv(session, schema, INDEX_FOR_CHART, PANEL_START, end)

    latest = factor_seq[-1] if factor_seq else None
    latest_signal = events[-1] if events else None  # 边沿触发: 最后一次方向切换 = 当前应做方向

    return {
        "overview": _build_overview(latest, latest_signal, index_bars),
        "chart": _build_chart(index_bars, comp, events),
        "accuracy": _build_accuracy(accuracy),
        "generated_at": int(time.time()),
        "sample_range": [str(comp[0].trade_date), str(comp[-1].trade_date)],
    }


def _base_panel(session: Any, schema: Any, force_refresh: bool = False) -> dict:
    """基础面板(三层缓存: 内存 30min → 库 24h → 现算+落库), 不含盘中实时 overlay。
    内存命中 <1ms; 库命中 <100ms; 现算+落库 ~16s(仅首次/过期/force)。"""
    now = time.time()
    if not force_refresh and _cache["panel"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["panel"]
    with _lock:
        if not force_refresh and _cache["panel"] and time.time() - _cache["ts"] < _CACHE_TTL:
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
    """盘中(交易时段)用实时指数 overlay: chart 最新K线 + overview 点位/涨跌。
    因子/信号保持昨日收盘; 不落库(实时变化); 非交易时段原样返回。"""
    if panel.get("empty") or not _is_intraday_china():
        return panel
    panel = dict(panel)  # 顶层浅 copy, 避免污染内存缓存里的 base panel
    try:
        detail = RealMarketDataClient().index_detail("000001", "SSE") or {}
    except Exception:  # noqa: BLE001  实时源不可用则退回昨日 panel
        return panel
    last_price = _to_float(detail.get("last_price"))
    volume = _to_float(detail.get("volume"))
    if not last_price or not volume or volume <= 0:
        return panel  # 盘前/停牌/节假日 volume=0 不 overlay
    today = _china_today().isoformat()
    today_bar = {
        "date": today,
        "open": _to_float(detail.get("open_price")) or last_price,
        "close": last_price,
        "high": _to_float(detail.get("high_price")) or last_price,
        "low": _to_float(detail.get("low_price")) or last_price,
        "volume": volume,
        "turnover": _to_float(detail.get("turnover")) or _to_float(detail.get("amount")) or 0.0,
    }
    chart = dict(panel.get("chart") or {})
    bars = list(chart.get("bars") or [])
    if bars and bars[-1].get("date") == today:
        bars[-1] = today_bar
    else:
        bars.append(today_bar)
    panel["chart"] = {**chart, "bars": bars}
    ov = dict(panel.get("overview") or {})
    ov["index_close"] = last_price
    chg = _to_float(detail.get("change_pct"))
    if chg is not None:
        ov["index_change_pct"] = round(chg, 2)
    ov["latest_date"] = today
    ov["is_intraday"] = True
    panel["overview"] = ov
    return panel


def get_market_timing_panel(session: Any, schema: Any, force_refresh: bool = False) -> dict:
    """获取大盘择时面板(基础面板 + 盘中实时 overlay)。

    基础面板三层缓存(内存/库/现算), 含昨日收盘的因子与信号;
    盘中交易时段再 overlay 今天实时点位到 chart 最新K线 + overview。
    """
    return _overlay_intraday(_base_panel(session, schema, force_refresh))
