"""低吸日线实时推荐服务：后台扫描 + 持久化快照读取。

盘中（09:25-15:30 工作日）用全市场现货快照给每只股票合成一根今日虚拟
日线（最新价当收盘），与历史日线拼接后走同一套研究票规则扫描和诊断评分；
盘后等 stock_daily_bars 统一同步落地后自动切换为确认日线。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select, text

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.low_suction.daily_factor_repository import (
    load_daily_factor_inputs,
)
from alphaagent.server.services.low_suction.daily_picks_backtest import (
    BACKTEST_VERSION,
    build_backtest_payload,
)
from alphaagent.server.services.low_suction.daily_picks_repository import (
    create_daily_backtest_rebuild_run,
    load_daily_backtest_run,
    load_daily_backtest_rebuild_runs,
    save_daily_backtest_run,
    update_daily_backtest_rebuild_run,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
    candidate_ranking_key,
    scan_low_suction_candidates,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import SCORE_VERSION
from alphaagent.server.services.low_suction.live_scan_repository import (
    load_live_scan_runs,
    save_live_scan_run,
)
from alphaagent.server.services.low_suction.live_snapshot_repository import (
    load_live_snapshot,
    save_live_snapshot,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
LIVE_SCAN_INTERVAL_SECONDS = 15 * 60
LIVE_LOOKBACK_CALENDAR_DAYS = 10  # 加载日历窗口；特征 warmup 由加载器另加 120 天
LIVE_MAX_ITEMS_PER_FAMILY = 100
LIVE_PAGE_SIZE = 20
SPOT_MERGE_START = time(9, 25)
SPOT_MERGE_END = time(15, 30)
MIN_SPOT_ACTIVE_SYMBOLS = 3_000

_logger = logging.getLogger(__name__)
_inputs_cache_lock = threading.Lock()
# 日线输入按“最新可靠交易日”缓存：后台定时重扫不重读库。
_inputs_cache: dict[str, object] = {"key": None, "inputs": None}
_LIVE_SCAN_ADVISORY_LOCK_KEY = 8_218_134_158
_fallback_live_scan_execution_lock = threading.Lock()


class LiveScanAlreadyRunningError(RuntimeError):
    """Raised when another process owns the low-suction live scan."""


@contextmanager
def _live_scan_execution_lock() -> Iterator[None]:
    """Keep scheduled scans single-flight across worker processes."""

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        if not _fallback_live_scan_execution_lock.acquire(blocking=False):
            raise LiveScanAlreadyRunningError("低吸实时扫描已有后台任务在执行")
        try:
            yield
        finally:
            _fallback_live_scan_execution_lock.release()
        return

    with engine.connect() as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": _LIVE_SCAN_ADVISORY_LOCK_KEY},
            ).scalar_one()
        )
        connection.commit()
        if not acquired:
            raise LiveScanAlreadyRunningError("低吸实时扫描已有后台任务在执行")
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _LIVE_SCAN_ADVISORY_LOCK_KEY},
            )
            connection.commit()


def get_live_recommendations(
    *,
    trend_page: int = 1,
    oversold_page: int = 1,
) -> dict[str, object]:
    """Read a persisted snapshot and return independent family pages."""

    now = datetime.now(SHANGHAI)
    payload = load_live_snapshot(SCORE_VERSION)
    if payload is None:
        return {
            "status": "unavailable",
            "message": "后台首次扫描中，请稍后刷新",
            "refresh_interval_seconds": LIVE_SCAN_INTERVAL_SECONDS,
            "score_version": SCORE_VERSION,
            "scan_trace": _load_live_scan_trace(now.date()),
        }

    result = dict(payload)
    result["refresh_interval_seconds"] = LIVE_SCAN_INTERVAL_SECONDS
    result["scan_trace"] = _load_live_scan_trace(
        _payload_trade_date(result, now.date())
    )
    return _paginate_live_payload(
        result, trend_page=trend_page, oversold_page=oversold_page
    )


def refresh_live_recommendations() -> dict[str, object]:
    """Scan once in the scheduler worker, then replace the readable snapshot."""

    with _live_scan_execution_lock():
        started_at = datetime.now(SHANGHAI)
        try:
            payload = _compute_live_payload(started_at)
            payload.setdefault("trade_date", started_at.date().isoformat())
            payload["refresh_interval_seconds"] = LIVE_SCAN_INTERVAL_SECONDS
            save_live_snapshot(payload)
        except Exception as exc:
            _record_failed_live_scan(started_at, datetime.now(SHANGHAI), exc)
            raise

        _attach_live_scan_trace(payload, started_at, datetime.now(SHANGHAI))
        return payload


def get_daily_backtest_report() -> dict[str, object] | None:
    """Read the materialized backtest payload (CLI 写库，API 读库）。"""

    payload = load_daily_backtest_run()
    if payload is None:
        return None
    if (
        payload.get("version") != BACKTEST_VERSION
        or payload.get("score_version") != SCORE_VERSION
    ):
        return None
    return _normalize_unsettled_ledger_day_returns(payload)


def _normalize_unsettled_ledger_day_returns(
    payload: dict[str, object],
) -> dict[str, object]:
    """Correct legacy zero returns for ledger days with no settled D+1 legs."""

    ledger_days = payload.get("ledger_days")
    if not isinstance(ledger_days, list):
        return payload

    normalized_days: list[object] = []
    changed = False
    for day in ledger_days:
        if not isinstance(day, dict):
            normalized_days.append(day)
            continue
        legs = day.get("legs")
        all_legs_unsettled = (
            isinstance(legs, list)
            and bool(legs)
            and all(
                isinstance(leg, dict) and leg.get("d1_close_return_pct") is None
                for leg in legs
            )
        )
        if all_legs_unsettled and day.get("day_return_pct") is not None:
            normalized_days.append({**day, "day_return_pct": None})
            changed = True
        else:
            normalized_days.append(day)

    return {**payload, "ledger_days": normalized_days} if changed else payload


# 回测物化：后台线程 + 状态（仿 limit_up history_service 的 rebuild 模式）。
# 全量扫描 ~69 万候选耗时数分钟，不能在 API 请求线程同步跑。
_REBUILD_LOCK = threading.RLock()
_REBUILD_THREAD: threading.Thread | None = None
_REBUILD_STATE: dict[str, object] = {"status": "idle"}
_DAILY_BACKTEST_ADVISORY_LOCK_KEY = 8_218_134_157
_fallback_daily_backtest_execution_lock = threading.Lock()
BacktestProgressCallback = Callable[[str, str, dict[str, object]], None]


class DailyBacktestAlreadyRunningError(RuntimeError):
    """Raised when another AlphaAgent process owns the daily backtest rebuild."""


@contextmanager
def _daily_backtest_execution_lock() -> Iterator[None]:
    """Ensure the API and scheduler cannot rebuild the same report concurrently."""

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        if not _fallback_daily_backtest_execution_lock.acquire(blocking=False):
            raise DailyBacktestAlreadyRunningError("低吸日线回测已有服务器任务在执行")
        try:
            yield
        finally:
            _fallback_daily_backtest_execution_lock.release()
        return

    with engine.connect() as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": _DAILY_BACKTEST_ADVISORY_LOCK_KEY},
            ).scalar_one()
        )
        connection.commit()
        if not acquired:
            raise DailyBacktestAlreadyRunningError("低吸日线回测已有服务器任务在执行")
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _DAILY_BACKTEST_ADVISORY_LOCK_KEY},
            )
            connection.commit()


def run_daily_backtest_sync(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    progress: BacktestProgressCallback | None = None,
) -> dict[str, object]:
    """Synchronously rebuild and persist the daily backtest payload."""

    with _daily_backtest_execution_lock():
        return _run_daily_backtest_sync_unlocked(
            start_date=start_date,
            end_date=end_date,
            progress=progress,
        )


def _run_daily_backtest_sync_unlocked(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    progress: BacktestProgressCallback | None = None,
) -> dict[str, object]:
    """Rebuild the report while the cross-process execution lock is held."""

    _report_backtest_stage(progress, "load_inputs", "加载日线与证券状态", {})
    inputs = load_daily_factor_inputs(
        start_date=start_date,
        end_date=end_date,
        price_basis="raw_unadjusted",
    )
    _report_backtest_stage(
        progress,
        "scan_candidates",
        "扫描全市场候选",
        {
            "bar_rows": int(len(inputs.bars)),
            "trade_days": len(inputs.market_calendar),
        },
    )
    candidates = scan_low_suction_candidates(
        inputs.bars,
        inputs.market_calendar,
        inputs.security_status.to_dict(orient="records"),
    )
    _report_backtest_stage(
        progress,
        "resolve_names",
        "补全股票名称并筛除当前 ST 股",
        {"candidate_count": len(candidates)},
    )
    names = _load_stock_names({item.vt_symbol for item in candidates})
    candidates = _exclude_current_st_candidates(candidates, names)
    _report_backtest_stage(
        progress,
        "build_report",
        "汇总分数段、前五组合与市况复核",
        {"candidate_count": len(candidates)},
    )
    payload = build_backtest_payload(
        candidates,
        inputs.market_calendar,
        names=names,
        market_regimes=_load_market_regimes(inputs.market_calendar),
    )
    _report_backtest_stage(
        progress,
        "persist_report",
        "写入回测报告",
        {"labeled": int((payload.get("coverage") or {}).get("labeled") or 0)},
    )
    save_daily_backtest_run(BACKTEST_VERSION, payload)
    return payload


def start_daily_backtest_rebuild() -> dict[str, object]:
    """Launch the backtest rebuild in a background thread (returns immediately)."""

    global _REBUILD_THREAD
    with _REBUILD_LOCK:
        if _REBUILD_THREAD is not None and _REBUILD_THREAD.is_alive():
            message = _active_rebuild_message()
            _record_duplicate_rebuild_request(message)
            return {**_REBUILD_STATE, "already_running": True, "message": message}

        started_at = datetime.now(timezone.utc)
        run_id = _create_rebuild_run(started_at)
        _set_rebuild_state(
            status="building",
            run_id=run_id,
            source="manual",
            stage="load_inputs",
            message="加载日线与证券状态",
            started_at=started_at.isoformat(),
            stage_started_at=started_at.isoformat(),
            error=None,
        )
        _REBUILD_THREAD = threading.Thread(
            target=_background_daily_backtest_rebuild,
            args=(run_id,),
            name="low-suction-backtest-rebuild",
            daemon=True,
        )
        _REBUILD_THREAD.start()
        return dict(_REBUILD_STATE)


def _background_daily_backtest_rebuild(run_id: int | None) -> None:
    try:
        payload = run_daily_backtest_sync(
            progress=lambda stage, message, metrics: _update_rebuild_progress(
                run_id,
                stage=stage,
                message=message,
                metrics=metrics,
            )
        )
        coverage = payload.get("coverage") or {}
        finished_at = datetime.now(timezone.utc)
        _set_rebuild_state(
            status="ready",
            stage="completed",
            message="回测报告已写入",
            finished_at=finished_at.isoformat(),
            error=None,
            trade_days=coverage.get("trade_days"),
            labeled=coverage.get("labeled"),
        )
        _update_rebuild_run(
            run_id,
            status="ready",
            stage="completed",
            message="回测报告已写入",
            metrics={
                "trade_days": int(coverage.get("trade_days") or 0),
                "candidate_count": int(coverage.get("candidates") or 0),
                "labeled": int(coverage.get("labeled") or 0),
            },
            finished_at=finished_at,
        )
    except Exception as exc:  # noqa: BLE001
        finished_at = datetime.now(timezone.utc)
        error = {"type": exc.__class__.__name__, "message": str(exc)}
        _set_rebuild_state(
            status="failed",
            stage="failed",
            message="回测执行失败",
            finished_at=finished_at.isoformat(),
            error=error,
        )
        _update_rebuild_run(
            run_id,
            status="failed",
            stage="failed",
            message="回测执行失败",
            error=f"{error['type']}: {error['message']}"[:500],
            finished_at=finished_at,
        )


def get_daily_backtest_rebuild_status() -> dict[str, object]:
    """Read the current rebuild state for frontend polling."""

    with _REBUILD_LOCK:
        status = dict(_REBUILD_STATE)
    try:
        status["recent_runs"] = load_daily_backtest_rebuild_runs()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction backtest run history read failed: %s", exc)
        status["recent_runs"] = []
    return status


def _set_rebuild_state(**values: object) -> None:
    with _REBUILD_LOCK:
        _REBUILD_STATE.update(values)


def _report_backtest_stage(
    progress: BacktestProgressCallback | None,
    stage: str,
    message: str,
    metrics: dict[str, object],
) -> None:
    if progress is not None:
        progress(stage, message, metrics)


def _create_rebuild_run(started_at: datetime) -> int | None:
    try:
        return create_daily_backtest_rebuild_run(
            source="manual",
            status="running",
            stage="load_inputs",
            strategy_version=BACKTEST_VERSION,
            score_version=SCORE_VERSION,
            message="加载日线与证券状态",
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction backtest run record create failed: %s", exc)
        return None


def _record_duplicate_rebuild_request(message: str) -> None:
    try:
        now = datetime.now(timezone.utc)
        create_daily_backtest_rebuild_run(
            source="manual",
            status="already_running",
            stage="request_rejected",
            strategy_version=BACKTEST_VERSION,
            score_version=SCORE_VERSION,
            message=message,
            finished_at=now,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction duplicate backtest request record failed: %s", exc)


def _active_rebuild_message() -> str:
    run_id = _REBUILD_STATE.get("run_id")
    stage = str(_REBUILD_STATE.get("stage") or "全量扫描")
    prefix = f"回测 #{run_id}" if run_id is not None else "已有回测"
    return f"{prefix} 正在 {stage}，本次请求未新建任务"


def _update_rebuild_progress(
    run_id: int | None,
    *,
    stage: str,
    message: str,
    metrics: dict[str, object],
) -> None:
    now = datetime.now(timezone.utc)
    _set_rebuild_state(
        stage=stage,
        message=message,
        stage_started_at=now.isoformat(),
        metrics=metrics,
    )
    _update_rebuild_run(
        run_id,
        stage=stage,
        message=message,
        metrics=metrics,
    )


def _update_rebuild_run(run_id: int | None, **values: object) -> None:
    if run_id is None:
        return
    try:
        update_daily_backtest_rebuild_run(run_id, **values)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction backtest run record update failed: %s", exc)


def _attach_live_scan_trace(
    payload: dict[str, object],
    started_at: datetime,
    finished_at: datetime,
) -> None:
    """Persist a completed scan and expose its signal-day execution timeline."""

    trade_date = _payload_trade_date(payload, started_at.date())
    try:
        save_live_scan_run(
            {
                "trade_date": trade_date,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": _elapsed_milliseconds(started_at, finished_at),
                "status": str(payload.get("status") or "ok"),
                "provisional": payload.get("provisional"),
                "spot_active_symbols": payload.pop("_scan_spot_active_symbols", None),
                "trend_count": _family_total(payload.get("trend")),
                "oversold_count": _family_total(payload.get("oversold")),
                "score_version": SCORE_VERSION,
                "merge_note": payload.get("merge_note"),
            }
        )
        payload["scan_trace"] = load_live_scan_runs(trade_date)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction live scan trace write failed: %s", exc)


def _load_live_scan_trace(trade_date: date) -> list[dict[str, object]]:
    """Read diagnostics without making a healthy snapshot unavailable."""

    try:
        return load_live_scan_runs(trade_date)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction live scan trace read failed: %s", exc)
        return []


def _record_failed_live_scan(
    started_at: datetime,
    finished_at: datetime,
    error: Exception,
) -> None:
    """Best-effort error record that never changes the original scan failure."""

    try:
        save_live_scan_run(
            {
                "trade_date": started_at.date(),
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": _elapsed_milliseconds(started_at, finished_at),
                "status": "error",
                "score_version": SCORE_VERSION,
                "error": f"{error.__class__.__name__}: {error}"[:500],
            }
        )
    except Exception as trace_error:  # noqa: BLE001
        _logger.warning("low-suction failed scan trace write failed: %s", trace_error)


def _payload_trade_date(payload: dict[str, object], fallback: date) -> date:
    value = payload.get("trade_date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return fallback


def _family_total(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    total = value.get("total")
    return int(total) if total is not None else None


def _elapsed_milliseconds(started_at: datetime, finished_at: datetime) -> int:
    return max(int((finished_at - started_at).total_seconds() * 1_000), 0)


def _live_inputs(now: datetime):
    """Load daily inputs once per latest reliable trade date (day-level cache)."""

    probe_start = now.date() - timedelta(days=LIVE_LOOKBACK_CALENDAR_DAYS)
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date, func.count())
            .where(schema.stock_daily_bars.c.trade_date >= probe_start)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()
    reliable = [row[0] for row in rows if int(row[1] or 0) >= 3_000]
    latest = reliable[-1] if reliable else None
    with _inputs_cache_lock:
        if latest is not None and _inputs_cache.get("key") == latest:
            return _inputs_cache["inputs"]
    inputs = load_daily_factor_inputs(
        start_date=probe_start,
        end_date=None,
        price_basis="raw_unadjusted",
    )
    with _inputs_cache_lock:
        _inputs_cache["key"] = latest
        _inputs_cache["inputs"] = inputs
    return inputs


def _compute_live_payload(now: datetime) -> dict[str, object]:
    inputs = _live_inputs(now)
    calendar = list(inputs.market_calendar)
    bars = inputs.bars
    provisional = False
    merge_note = None
    spot_active_symbols: int | None = None
    if not calendar:
        return {
            "status": "unavailable",
            "message": "无可靠市场日历，请检查日线数据同步",
            "asof": now.isoformat(timespec="seconds"),
            "score_version": SCORE_VERSION,
            "_scan_spot_active_symbols": spot_active_symbols,
        }

    latest_bar_date = calendar[-1]
    if _should_merge_spot(now, latest_bar_date):
        merged, active = _merge_spot_bars(bars, now.date())
        spot_active_symbols = active
        if active >= MIN_SPOT_ACTIVE_SYMBOLS:
            bars = merged
            calendar = [*calendar, now.date()]
            provisional = now.time() < time(15, 5)
            merge_note = (
                f"盘中虚拟K线（{active} 只有成交股票，最新价当收盘）"
                if provisional
                else "盘后现货快照合成当日K线（等待日线同步确认）"
            )
        else:
            merge_note = f"现货快照有效股票不足（{active} 只），沿用最近完整日线"

    target_date = calendar[-1]
    # 只扫描目标日，但保留完整市场日历来核对“前一交易日”的包裹后确认。
    candidates = scan_low_suction_candidates(
        bars,
        calendar,
        inputs.security_status.to_dict(orient="records"),
        target_dates={target_date},
    )
    names = _load_stock_names({item.vt_symbol for item in candidates})
    trend = _family_payload(candidates, "trend_pullback", names)
    oversold = _family_payload(candidates, "oversold_rebound", names)
    return {
        "status": "ok",
        "asof": now.isoformat(timespec="seconds"),
        "trade_date": target_date.isoformat(),
        "provisional": provisional,
        "merge_note": merge_note,
        "refresh_interval_seconds": LIVE_SCAN_INTERVAL_SECONDS,
        "score_version": SCORE_VERSION,
        "backtest_version": BACKTEST_VERSION,
        "trend": trend,
        "oversold": oversold,
        "label_convention": "raw_unadjusted 探索级 · D 日收盘买入、D+1 收盘结算 · 未扣费",
        "_scan_spot_active_symbols": spot_active_symbols,
    }


def _family_payload(
    candidates: list[LowSuctionCandidate],
    setup_type: str,
    names: dict[str, str],
) -> dict[str, object]:
    pool = [item for item in candidates if item.setup_type == setup_type]
    pool = [item for item in pool if not _is_st_name(names.get(item.vt_symbol))]
    # 与回测同一决胜键：分数 → 连续小 K 线数 → 换手率(低优先) → 代码
    pool.sort(key=candidate_ranking_key)
    items: list[dict[str, object]] = []
    for rank, candidate in enumerate(pool[:LIVE_MAX_ITEMS_PER_FAMILY], start=1):
        row = candidate.as_dict()
        row["stock_name"] = names.get(candidate.vt_symbol)
        row["rank"] = rank
        row.pop("d1_close_return_pct", None)
        row.pop("d1_trade_date", None)
        items.append(row)
    return {
        "total": len(pool),
        "limit": LIVE_MAX_ITEMS_PER_FAMILY,
        "items": items,
    }


def _exclude_current_st_candidates(
    candidates: list[LowSuctionCandidate],
    names: dict[str, str],
) -> list[LowSuctionCandidate]:
    """Keep the exploratory historical pool consistent with the live ST screen."""

    return [
        candidate
        for candidate in candidates
        if not _is_st_name(names.get(candidate.vt_symbol))
    ]


def _paginate_live_payload(
    payload: dict[str, object],
    *,
    trend_page: int,
    oversold_page: int,
) -> dict[str, object]:
    """Page the persisted top-100 snapshot without rerunning the market scan."""

    result = dict(payload)
    for setup_type, requested_page in (
        ("trend", trend_page),
        ("oversold", oversold_page),
    ):
        family = payload.get(setup_type)
        if not isinstance(family, dict):
            continue
        all_items = list(family.get("items") or [])
        pages = max(1, (len(all_items) + LIVE_PAGE_SIZE - 1) // LIVE_PAGE_SIZE)
        page = min(max(1, requested_page), pages)
        start = (page - 1) * LIVE_PAGE_SIZE
        result[setup_type] = {
            **family,
            "items": all_items[start : start + LIVE_PAGE_SIZE],
            "page": page,
            "page_size": LIVE_PAGE_SIZE,
            "pages": pages,
        }
    return result


def _load_market_regimes(calendar: tuple[date, ...]) -> dict[date, str]:
    """Classify signal days by same-day Shanghai Composite close versus MA20."""

    if not calendar:
        return {}
    start = calendar[0] - timedelta(days=45)
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date, schema.stock_daily_bars.c.close_price)
            .where(
                schema.stock_daily_bars.c.vt_symbol == "000001.SSE",
                schema.stock_daily_bars.c.trade_date >= start,
                schema.stock_daily_bars.c.trade_date <= calendar[-1],
            )
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()
    closes: list[tuple[date, float]] = [
        (row[0], float(row[1])) for row in rows if row[1] is not None
    ]
    regimes: dict[date, str] = {}
    for index in range(19, len(closes)):
        trade_date, close_price = closes[index]
        ma20 = sum(value for _, value in closes[index - 19 : index + 1]) / 20
        regimes[trade_date] = "above_ma20" if close_price >= ma20 else "below_ma20"
    return regimes


def _should_merge_spot(now: datetime, latest_bar_date: date) -> bool:
    if now.date() <= latest_bar_date:
        return False
    if now.weekday() >= 5:
        return False
    return SPOT_MERGE_START <= now.time() <= SPOT_MERGE_END


def _merge_spot_bars(bars: pd.DataFrame, today: date) -> tuple[pd.DataFrame, int]:
    """Append synthetic today bars from the full-market spot snapshot."""

    try:
        from alphaagent.data_sources.akshare_adapter import (
            AkShareAdapter,
            _stock_row_to_api,
        )

        raw_rows = AkShareAdapter()._all_stock_spot_rows()  # noqa: SLF001
        rows = [_stock_row_to_api(row) for row in raw_rows]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction live spot snapshot unavailable: %s", exc)
        return bars, 0
    existing = (
        set(bars.loc[bars["trade_date"] == today, "vt_symbol"]) if not bars.empty else set()
    )
    synthetic: list[dict[str, object]] = []
    for row in rows:
        vt_symbol = str(row.get("vt_symbol") or "")
        if not vt_symbol or vt_symbol in existing or not _is_main_board(vt_symbol):
            continue
        last = _float(row.get("last_price"))
        open_price = _float(row.get("open_price"))
        high = _float(row.get("high_price"))
        low = _float(row.get("low_price"))
        volume = _float(row.get("volume"))
        if not last or not open_price or not high or not low or not volume:
            continue
        synthetic.append(
            {
                "vt_symbol": vt_symbol,
                "trade_date": today,
                "open_price": open_price,
                "close_price": last,
                "high_price": max(high, open_price, last),
                "low_price": min(low, open_price, last),
                "volume": volume,
                "turnover": _float(row.get("turnover")),
                "turnover_rate": _float(row.get("turnover_rate")),
                "source": "akshare_spot_intraday",
                "updated_at": None,
            }
        )
    if not synthetic:
        return bars, 0
    frame = pd.concat([bars, pd.DataFrame(synthetic)], ignore_index=True)
    return frame, len(synthetic)


def _load_stock_names(vt_symbols: set[str]) -> dict[str, str]:
    if not vt_symbols:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(schema.stocks.c.vt_symbol, schema.stocks.c.name).where(
                schema.stocks.c.vt_symbol.in_(tuple(vt_symbols))
            )
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _is_st_name(name: str | None) -> bool:
    return bool(name) and "ST" in name.upper()


def _is_main_board(vt_symbol: str) -> bool:
    symbol, _, exchange = vt_symbol.partition(".")
    if exchange == "SSE":
        return symbol.startswith(("600", "601", "603", "605"))
    if exchange == "SZSE":
        return symbol.startswith(("000", "001", "002", "003"))
    return False


def _float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
