"""低吸日线实时推荐服务：分钟虚拟 K 线 + 按交易日持久化快照。

盘中用全市场现货 OHLCV 合成今日虚拟日 K，按分钟重算同一套日线规则；
15:01 固化尾盘虚拟 K，晚间完整日线同步完成后以确认日线覆盖同一交易日。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select, text

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
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
    list_live_snapshot_dates,
    load_live_snapshot,
    save_live_snapshot,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
# 回测默认窗口：最近两年（日历日 ≈ 490 个交易日）。
DEFAULT_BACKTEST_WINDOW_DAYS = 732
LIVE_SCAN_INTERVAL_SECONDS = 60
LIVE_LOOKBACK_CALENDAR_DAYS = 10  # 加载日历窗口；特征 warmup 由加载器另加 120 天
LIVE_MAX_ITEMS_PER_FAMILY = 100
LIVE_PAGE_SIZE = 20
SPOT_MERGE_START = time(9, 25)
TAIL_FINAL_TIME = time(15, 1)
# 15:01 is the one tail snapshot.  Daily-bar confirmation happens later and
# does not depend on another spot merge.
SPOT_MERGE_END = TAIL_FINAL_TIME
TAIL_FINAL_RETRY_END = time(15, 30)
MIN_SPOT_ACTIVE_SYMBOLS = 3_000

SNAPSHOT_PHASE_INTRADAY = "intraday"
SNAPSHOT_PHASE_TAIL_FINAL = "tail_final"
SNAPSHOT_PHASE_CONFIRMED = "confirmed"

_logger = logging.getLogger(__name__)
_inputs_cache_lock = threading.Lock()
# 日线输入按“最新可靠交易日”缓存：后台定时重扫不重读库。
_inputs_cache: dict[str, object] = {"key": None, "inputs": None}
_LIVE_SCAN_ADVISORY_LOCK_KEY = 8_218_134_158
_fallback_live_scan_execution_lock = threading.Lock()


class LiveScanAlreadyRunningError(RuntimeError):
    """Raised when another process owns the low-suction live scan."""


@dataclass(frozen=True)
class SpotBarMerge:
    """One attempt to append provisional daily bars from a spot snapshot."""

    bars: pd.DataFrame
    active_symbols: int
    total_symbols: int
    error: str | None = None


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
    trade_date: date | None = None,
) -> dict[str, object]:
    """Read a persisted snapshot and return independent family pages."""

    now = datetime.now(SHANGHAI)
    requested_date = trade_date
    if requested_date is None and now.weekday() < 5:
        requested_date = now.date()
    payload = (
        load_live_snapshot(SCORE_VERSION, trade_date=requested_date)
        if requested_date is not None
        else load_live_snapshot(SCORE_VERSION)
    )
    if payload is None:
        message = (
            f"{requested_date.isoformat()} 暂无低吸推荐快照"
            if requested_date is not None
            else "后台首次扫描中，请稍后刷新"
        )
        return {
            "status": "unavailable",
            "message": message,
            "trade_date": (requested_date or now.date()).isoformat(),
            "refresh_interval_seconds": LIVE_SCAN_INTERVAL_SECONDS,
            "score_version": SCORE_VERSION,
            "scan_trace": _load_live_scan_trace(requested_date or now.date()),
        }

    result = dict(payload)
    result["refresh_interval_seconds"] = LIVE_SCAN_INTERVAL_SECONDS
    result["scan_trace"] = _load_live_scan_trace(
        _payload_trade_date(result, now.date())
    )
    return _paginate_live_payload(
        result, trend_page=trend_page, oversold_page=oversold_page
    )


def get_live_recommendation_dates() -> list[str]:
    """Return stored recommendation dates, newest first, for the date switcher."""

    return list_live_snapshot_dates(SCORE_VERSION)


def refresh_live_recommendations(
    *,
    force_tail_final: bool = False,
) -> dict[str, object]:
    """Scan once in the scheduler worker, then replace the readable snapshot."""

    with _live_scan_execution_lock():
        started_at = datetime.now(SHANGHAI)
        try:
            scan_payload = (
                _compute_live_payload(started_at, force_tail_final=True)
                if force_tail_final
                else _compute_live_payload(started_at)
            )
            scan_payload.setdefault("trade_date", started_at.date().isoformat())
            scan_payload["refresh_interval_seconds"] = LIVE_SCAN_INTERVAL_SECONDS
            payload = _snapshot_payload_to_persist(
                scan_payload,
                started_at.date(),
                replace_tail_final=force_tail_final,
            )
            save_live_snapshot(payload)
        except Exception as exc:
            _record_failed_live_scan(started_at, datetime.now(SHANGHAI), exc)
            raise

        _attach_live_scan_trace(
            scan_payload,
            started_at,
            datetime.now(SHANGHAI),
            trade_date=started_at.date(),
        )
        if payload is not scan_payload:
            payload["scan_trace"] = scan_payload.get("scan_trace", [])
        return payload


def _snapshot_payload_to_persist(
    scan_payload: dict[str, object],
    today: date,
    *,
    replace_tail_final: bool = False,
) -> dict[str, object]:
    """Keep the 15:01 snapshot until a same-day confirmed bar supersedes it."""

    if _is_confirmed_today_payload(scan_payload, today):
        return scan_payload

    try:
        existing = load_live_snapshot(SCORE_VERSION, trade_date=today)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction tail snapshot lookup failed: %s", exc)
        return scan_payload

    if not isinstance(existing, dict):
        return scan_payload
    if (
        scan_payload.get("status") != "ok"
        and _is_current_day_success_payload(existing, today)
    ):
        return dict(existing)
    if existing.get("snapshot_phase") != SNAPSHOT_PHASE_TAIL_FINAL:
        return scan_payload
    if replace_tail_final and _is_tail_final_today_payload(scan_payload, today):
        return scan_payload
    return dict(existing)


def _is_confirmed_today_payload(payload: Mapping[str, object], today: date) -> bool:
    return (
        _payload_trade_date(dict(payload), today) == today
        and payload.get("snapshot_phase") == SNAPSHOT_PHASE_CONFIRMED
    )


def _is_tail_final_today_payload(payload: Mapping[str, object], today: date) -> bool:
    return (
        _payload_trade_date(dict(payload), today) == today
        and payload.get("snapshot_phase") == SNAPSHOT_PHASE_TAIL_FINAL
    )


def _is_current_day_success_payload(
    payload: Mapping[str, object],
    today: date,
) -> bool:
    return (
        _payload_trade_date(dict(payload), today) == today
        and payload.get("status") == "ok"
    )


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
    return payload


# 回测物化：后台线程 + 状态。
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

    # 默认窗口最近两年（主人 2026-08-16 口径）：全量 821 个交易日叠加
    # 新规则扫描成本在受限 CPU 下 >3 小时；两年 ~490 个交易日覆盖两轮
    # 牛熊 regime 足够验收，显式传参的研究路径不受影响。
    if start_date is None and end_date is None:
        end_date = datetime.now(SHANGHAI).date()
        start_date = end_date - timedelta(days=DEFAULT_BACKTEST_WINDOW_DAYS)
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
    market_regimes = _load_market_regimes(inputs.market_calendar)
    candidates = scan_low_suction_candidates(
        inputs.bars,
        inputs.market_calendar,
        inputs.security_status.to_dict(orient="records"),
        market_regimes=market_regimes,
        market_limit_up_counts=_load_market_limit_up_counts(
            inputs.market_calendar
        ),
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
        market_regimes=market_regimes,
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


def reconcile_materialized_views_on_startup() -> dict[str, str]:
    """启动自检：物化视图（live 快照/回测报告）版本漂移时立即后台补建。

    日常链路（盘中每分钟扫描 + 18:00 确认快照 + 22:30 全量回测）已覆盖
    常规刷新；此自检只补「代码/评分版本升级日」的缺口：容器重建后若当前
    SCORE_VERSION/BACKTEST_VERSION 没有任何物化数据，版本门禁会让页面
    整夜空白，必须立刻补，而不是等下一个同步档。
    """

    actions: dict[str, str] = {}
    if load_live_snapshot(SCORE_VERSION) is None:
        try:
            refresh_live_recommendations()
            actions["live_snapshot"] = "rebuilt"
        except LiveScanAlreadyRunningError:
            actions["live_snapshot"] = "already_running"
    else:
        actions["live_snapshot"] = "fresh"
    if get_daily_backtest_report() is None:
        result = start_daily_backtest_rebuild()
        actions["backtest_report"] = (
            "already_running" if result.get("already_running") else "rebuilding"
        )
    else:
        actions["backtest_report"] = "fresh"
    return actions


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
    """Read the current rebuild state for frontend polling.

    顶层状态以 DB 运行记录为准：回测可能由 worker 进程（启动自检/22:30 档）
    触发，本进程内存态不知道。内存 idle 但 DB 有 running 记录时，用该记录
    合成顶层 building 状态，前端轮询才能跨进程看到进度。
    """

    with _REBUILD_LOCK:
        status = dict(_REBUILD_STATE)
    try:
        status["recent_runs"] = load_daily_backtest_rebuild_runs()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction backtest run history read failed: %s", exc)
        status["recent_runs"] = []
    if status.get("status") != "building":
        active = next(
            (
                run
                for run in status["recent_runs"]
                if run.get("status") == "running"
            ),
            None,
        )
        if active is not None:
            status.update(
                {
                    "status": "building",
                    "run_id": active.get("id"),
                    "source": active.get("source"),
                    "stage": active.get("stage"),
                    "started_at": active.get("started_at") or active.get("requested_at"),
                    "message": active.get("message"),
                }
            )
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
    *,
    trade_date: date | None = None,
) -> None:
    """Persist a completed scan and expose its signal-day execution timeline."""

    trade_date = trade_date or _payload_trade_date(payload, started_at.date())
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
    cache_key = (latest, completed_daily_bar_cutoff(now))
    with _inputs_cache_lock:
        if latest is not None and _inputs_cache.get("key") == cache_key:
            return _inputs_cache["inputs"]
    inputs = load_daily_factor_inputs(
        start_date=probe_start,
        end_date=None,
        price_basis="raw_unadjusted",
    )
    with _inputs_cache_lock:
        _inputs_cache["key"] = cache_key
        _inputs_cache["inputs"] = inputs
    return inputs


def _compute_live_payload(
    now: datetime,
    *,
    force_tail_final: bool = False,
) -> dict[str, object]:
    inputs = _live_inputs(now)
    calendar = list(inputs.market_calendar)
    bars = inputs.bars
    today_has_confirmed_daily_bar = _today_has_confirmed_daily_bar(calendar, now)
    snapshot_phase = SNAPSHOT_PHASE_CONFIRMED
    merge_note = None
    spot_active_symbols: int | None = None
    if not calendar:
        return _unavailable_live_payload(
            now,
            "无可靠市场日历，请检查日线数据同步",
        )

    # A current-day row is not sufficient to mark the snapshot confirmed.  It
    # must first pass the same daily cutoff and cross-sectional coverage gate
    # that produced the reliable market calendar.
    if not today_has_confirmed_daily_bar:
        calendar, bars = _without_today_bars(calendar, bars, now.date())
    if not calendar:
        return _unavailable_live_payload(
            now,
            "无可用的完整日线，暂不能生成今日低吸推荐",
        )

    latest_bar_date = calendar[-1]
    should_merge_spot = _should_merge_spot(now, latest_bar_date)
    if force_tail_final and _tail_final_retry_open(now, latest_bar_date):
        should_merge_spot = True
    if should_merge_spot:
        if force_tail_final:
            spot_merge = _merge_spot_bars(
                bars,
                now.date(),
                force_refresh=True,
            )
        else:
            spot_merge = _merge_spot_bars(bars, now.date())
        spot_active_symbols = spot_merge.active_symbols
        if spot_merge.error:
            merge_note = (
                f"现货快照获取失败（{spot_merge.error}）"
            )
            return _unavailable_live_payload(
                now,
                f"{merge_note}，暂不能生成今日低吸推荐",
                merge_note=merge_note,
                spot_active_symbols=spot_active_symbols,
            )
        elif spot_merge.active_symbols >= MIN_SPOT_ACTIVE_SYMBOLS:
            bars = spot_merge.bars
            calendar = [*calendar, now.date()]
            snapshot_phase = (
                SNAPSHOT_PHASE_TAIL_FINAL
                if force_tail_final or now.time() >= TAIL_FINAL_TIME
                else SNAPSHOT_PHASE_INTRADAY
            )
            merge_note = (
                "盘中虚拟K线（"
                f"{spot_merge.active_symbols} 只有成交股票，最新价当收盘）"
                if snapshot_phase == SNAPSHOT_PHASE_INTRADAY
                else "尾盘虚拟K线已固化（等待完整日线同步确认）"
            )
        else:
            merge_note = (
                "现货快照 OHLCV 覆盖不足（"
                f"{spot_merge.active_symbols}/{spot_merge.total_symbols} 只可用，"
                f"至少 {MIN_SPOT_ACTIVE_SYMBOLS} 只）"
            )
            return _unavailable_live_payload(
                now,
                f"{merge_note}，暂不能生成今日低吸推荐",
                merge_note=merge_note,
                spot_active_symbols=spot_active_symbols,
            )
    elif (
        now.weekday() < 5
        and latest_bar_date < now.date()
        and not today_has_confirmed_daily_bar
    ):
        return _unavailable_live_payload(
            now,
            "当前不在可用的盘中扫描时段，暂不能生成今日低吸推荐",
        )

    target_date = calendar[-1]
    # 只扫描目标日，但保留完整市场日历来核对“前一交易日”的包裹后确认。
    # 弱市门（X 子型）用已确认指数日线分类；盘中今日未定型时由扫描器
    # 回退到最近已确认交易日（因果）。
    candidates = scan_low_suction_candidates(
        bars,
        calendar,
        inputs.security_status.to_dict(orient="records"),
        target_dates={target_date},
        market_regimes=_load_market_regimes(tuple(calendar)),
        market_limit_up_counts=_load_market_limit_up_counts(tuple(calendar)),
    )
    names = _load_stock_names({item.vt_symbol for item in candidates})
    trend = _family_payload(candidates, "trend_pullback", names)
    oversold = _family_payload(candidates, "oversold_rebound", names)
    return {
        "status": "ok",
        "asof": now.isoformat(timespec="seconds"),
        "trade_date": target_date.isoformat(),
        "snapshot_phase": snapshot_phase,
        "provisional": snapshot_phase != SNAPSHOT_PHASE_CONFIRMED,
        "merge_note": merge_note,
        "refresh_interval_seconds": LIVE_SCAN_INTERVAL_SECONDS,
        "score_version": SCORE_VERSION,
        "backtest_version": BACKTEST_VERSION,
        "trend": trend,
        "oversold": oversold,
        "label_convention": "raw_unadjusted 探索级 · D 日收盘买入、D+1 收盘结算 · 未扣费",
        "_scan_spot_active_symbols": spot_active_symbols,
    }


def _unavailable_live_payload(
    now: datetime,
    message: str,
    *,
    merge_note: str | None = None,
    spot_active_symbols: int | None = None,
) -> dict[str, object]:
    """Represent a failed current-day scan without substituting yesterday's picks."""

    return {
        "status": "unavailable",
        "message": message,
        "asof": now.isoformat(timespec="seconds"),
        "trade_date": now.date().isoformat(),
        "provisional": True,
        "merge_note": merge_note,
        "refresh_interval_seconds": LIVE_SCAN_INTERVAL_SECONDS,
        "score_version": SCORE_VERSION,
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


def _load_market_limit_up_counts(calendar: tuple[date, ...]) -> dict[date, int]:
    """每日全市场（主板）收盘涨停家数——趋势族 A 路径的情绪温度加分。"""

    if not calendar:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_limit_up_daily.c.trade_date,
                func.count(),
            )
            .where(
                schema.stock_limit_up_daily.c.is_limit_up.is_(True),
                schema.stock_limit_up_daily.c.trade_date >= calendar[0],
                schema.stock_limit_up_daily.c.trade_date <= calendar[-1],
                schema.stock_limit_up_daily.c.vt_symbol.op("~")(
                    "^(600|601|603|605|000|001|002|003)"
                ),
            )
            .group_by(schema.stock_limit_up_daily.c.trade_date)
        ).all()
    return {row[0]: int(row[1]) for row in rows}


def _today_has_confirmed_daily_bar(calendar: list[date], now: datetime) -> bool:
    """Whether today's bar passed the completed-session reliability gate."""

    return (
        now.weekday() < 5
        and now.date() in calendar
        and completed_daily_bar_cutoff(now) >= now.date()
    )


def _without_today_bars(
    calendar: list[date],
    bars: pd.DataFrame,
    today: date,
) -> tuple[list[date], pd.DataFrame]:
    filtered_calendar = [value for value in calendar if value < today]
    if not filtered_calendar or bars.empty:
        return filtered_calendar, bars
    return filtered_calendar, bars.loc[bars["trade_date"] < today].copy()


def _should_merge_spot(now: datetime, latest_bar_date: date) -> bool:
    if now.date() <= latest_bar_date:
        return False
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return (
        SPOT_MERGE_START <= current_time <= time(11, 30)
        or time(13, 0) <= current_time <= SPOT_MERGE_END
    )


def _tail_final_retry_open(now: datetime, latest_bar_date: date) -> bool:
    return (
        now.date() > latest_bar_date
        and now.weekday() < 5
        and TAIL_FINAL_TIME <= now.time() <= TAIL_FINAL_RETRY_END
    )


def _merge_spot_bars(
    bars: pd.DataFrame,
    today: date,
    *,
    force_refresh: bool = False,
) -> SpotBarMerge:
    """Append synthetic today bars from the full-market spot snapshot."""

    try:
        from alphaagent.data_sources.akshare_adapter import AkShareAdapter

        adapter = AkShareAdapter()
        snapshot = (
            adapter.all_stock_ohlcv_spot(force_refresh=True)
            if force_refresh
            else adapter.all_stock_ohlcv_spot()
        )
        raw_rows = snapshot.get("items")
        if not isinstance(raw_rows, list):
            raise RuntimeError("Sina OHLCV snapshot items missing")
        rows = [row for row in raw_rows if isinstance(row, dict)]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction live spot snapshot unavailable: %s", exc)
        return SpotBarMerge(
            bars=bars,
            active_symbols=0,
            total_symbols=0,
            error=f"{exc.__class__.__name__}: {str(exc)[:200]}",
        )
    if not rows:
        return SpotBarMerge(
            bars=bars,
            active_symbols=0,
            total_symbols=0,
            error="现货快照未返回任何股票",
        )
    main_board_rows = [
        row
        for row in rows
        if _is_main_board(str(row.get("vt_symbol") or ""))
    ]
    if not main_board_rows:
        return SpotBarMerge(
            bars=bars,
            active_symbols=0,
            total_symbols=0,
            error="现货快照未包含可用主板股票",
        )
    existing = (
        set(bars.loc[bars["trade_date"] == today, "vt_symbol"]) if not bars.empty else set()
    )
    synthetic: list[dict[str, object]] = []
    total_symbols = 0
    for row in main_board_rows:
        vt_symbol = str(row.get("vt_symbol") or "")
        if vt_symbol in existing:
            continue
        total_symbols += 1
        last = _float(row.get("last_price"))
        open_price = _float(row.get("open_price"))
        high = _float(row.get("high_price"))
        low = _float(row.get("low_price"))
        # 新浪快照 volume 单位是股，日线库存单位是手（1手=100股）。
        # 不换算会让合成 bar 的量能放大 100 倍，盘中所有缩量类
        # 规则（staircase_shrink / vol_monotone_6d 等）全天失配。
        volume = _float(row.get("volume"))
        if volume:
            volume = volume / 100.0
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
        return SpotBarMerge(
            bars=bars,
            active_symbols=0,
            total_symbols=total_symbols,
        )
    frame = pd.concat([bars, pd.DataFrame(synthetic)], ignore_index=True)
    frame = frame.sort_values(
        ["vt_symbol", "trade_date"],
        kind="stable",
        ignore_index=True,
    )
    return SpotBarMerge(
        bars=frame,
        active_symbols=len(synthetic),
        total_symbols=total_symbols,
    )


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
