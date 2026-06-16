"""Background orchestration for the public quant research workflow."""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from alphaagent.market.boards import normalize_included_boards
from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant import screening
from alphaagent.server.services.quant.factors import STRATEGY_ID
from alphaagent.server.services.quant.strategy_registry import get_strategy


_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_LATEST_JOB_ID: str | None = None
_JOB_KEEP_LIMIT = 20


class QuantResearchJobError(RuntimeError):
    """Raised when a quant research job cannot be read or started."""


def start_research_run(
    *,
    start: date | None = None,
    end: date | None = None,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    recommendation_limit: int = screening.DEFAULT_RECOMMENDATION_LIMIT,
    min_recommendation_score: float = 60.0,
    min_entry_score: float | None = None,
    persist: bool = True,
    auto_portfolio: bool = True,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
    initial_cash: float = 1_000_000,
    max_positions: int = 10,
    candidate_limit: int = 10,
    max_position_pct: float = 0.1,
    strict_entry: bool = True,
    execution_model: str = "legacy_next_open",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Start the full public research workflow in a daemon thread."""

    if not is_database_configured():
        raise QuantResearchJobError("DATABASE_URL is not configured")
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise QuantResearchJobError(f"Unsupported strategy: {strategy_id}")

    global _LATEST_JOB_ID
    with _JOB_LOCK:
        if _LATEST_JOB_ID:
            latest = _JOBS.get(_LATEST_JOB_ID)
            if latest and latest.get("status") == "running":
                return _copy_job(latest)

    boards = list(normalize_included_boards(included_boards))
    run_id = uuid4().hex
    created_at = _utc_now_iso()
    params = {
        "start": _date_text(start),
        "end": _date_text(end),
        "strategy": strategy.id,
        "max_symbols": int(max_symbols),
        "recommendation_limit": int(recommendation_limit),
        "min_recommendation_score": float(min_recommendation_score),
        "min_entry_score": float(min_entry_score if min_entry_score is not None else strategy.default_min_entry_score),
        "persist": bool(persist),
        "auto_portfolio": bool(auto_portfolio),
        "included_boards": boards,
        "initial_cash": float(initial_cash),
        "max_positions": int(max_positions),
        "candidate_limit": int(candidate_limit),
        "max_position_pct": float(max_position_pct),
        "strict_entry": bool(strict_entry),
        "execution_model": execution_model,
        "force_refresh": bool(force_refresh),
    }
    job = {
        "id": run_id,
        "status": "running",
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": None,
        "stage": "queued",
        "message": "准备运行策略研究",
        "progress_current": 0,
        "progress_total": 0,
        "progress_pct": 0,
        "params": params,
        "screen_run": None,
        "replay_run": None,
        "replay_run_id": None,
        "backtest_id": None,
        "backtest": None,
        "error_type": None,
        "error_detail": None,
    }
    with _JOB_LOCK:
        _JOBS[run_id] = job
        _LATEST_JOB_ID = run_id
        _trim_jobs_locked()

    thread = threading.Thread(
        target=_run_research_job,
        args=(run_id, start, end, params),
        name=f"quant-research-{run_id[:8]}",
        daemon=True,
    )
    thread.start()
    return get_research_run(run_id)


def get_research_run(run_id: str) -> dict[str, Any]:
    with _JOB_LOCK:
        job = _JOBS.get(run_id)
        if job is None:
            raise QuantResearchJobError(f"Unknown quant research run: {run_id}")
        return _copy_job(job)


def get_latest_research_run() -> dict[str, Any] | None:
    with _JOB_LOCK:
        if not _LATEST_JOB_ID:
            return None
        job = _JOBS.get(_LATEST_JOB_ID)
        return _copy_job(job) if job is not None else None


def _run_research_job(run_id: str, start: date | None, end: date | None, params: dict[str, Any]) -> None:
    try:
        _patch_job(run_id, {"stage": "screening", "message": "正在补齐候选交易日"})
        screen_result = screening.screen_stocks_range(
            start=start,
            end=end,
            strategy_id=str(params["strategy"]),
            max_symbols=int(params["max_symbols"]),
            recommendation_limit=int(params["recommendation_limit"]),
            min_recommendation_score=float(params["min_recommendation_score"]),
            persist=bool(params["persist"]),
            auto_portfolio=bool(params["auto_portfolio"]),
            included_boards=params["included_boards"],
            force_refresh=bool(params.get("force_refresh")),
            progress=_screen_progress(run_id),
        )
        _patch_job(
            run_id,
            {
                "screen_run": screen_result,
                "replay_run": screen_result.get("replay_run"),
                "replay_run_id": screen_result.get("replay_run_id"),
                "stage": "backtest",
                "message": "候选和买卖记录已生成，正在运行组合回测",
                "progress_current": 1,
                "progress_total": 1,
                "progress_pct": 90,
            },
        )
        if screen_result.get("status") not in {"ready", "empty"}:
            _finish_job(run_id, "failed", str(screen_result.get("message") or "候选生成失败"))
            return
        replay_run = screen_result.get("replay_run") if isinstance(screen_result.get("replay_run"), dict) else {}

        backtest_start = _parse_date_text(screen_result.get("start_date")) or start
        backtest_end = _parse_date_text(screen_result.get("end_date")) or end
        backtest = run_backtest(
            BacktestParams(
                strategy=str(params["strategy"]),
                start=backtest_start or date(2020, 1, 1),
                end=backtest_end,
                initial_cash=float(params["initial_cash"]),
                max_positions=int(params["max_positions"]),
                max_position_pct=float(params["max_position_pct"]),
                candidate_limit=int(params["candidate_limit"]),
                max_symbols=int(params["max_symbols"]),
                min_entry_score=float(params["min_entry_score"]),
                strict_entry=bool(params["strict_entry"]),
                execution_model=str(params["execution_model"]),
                included_boards=tuple(params["included_boards"]),
                persist=bool(params["persist"]),
            )
        )
        _patch_job(
            run_id,
            {
                "backtest": _compact_backtest(backtest),
                "backtest_id": backtest.get("backtest_id"),
                "progress_pct": 100,
                "message": "策略研究完成",
            },
        )
        if backtest.get("status") != "ready":
            _finish_job(run_id, "failed", _failure_message(backtest, replay_run))
            return
        _finish_job(run_id, "succeeded", "策略研究完成")
    except Exception as exc:
        _patch_job(run_id, {"error_type": exc.__class__.__name__, "error_detail": str(exc)})
        _finish_job(run_id, "failed", str(exc))


def _screen_progress(run_id: str) -> Callable[[dict[str, Any]], None]:
    def callback(patch: dict[str, Any]) -> None:
        current = int(patch.get("progress_current") or 0)
        total = int(patch.get("progress_total") or 0)
        trade_date = patch.get("trade_date")
        safe = {
            "stage": "screening",
            "progress_current": current,
            "progress_total": total,
            "progress_pct": round(min(current / total * 85, 85), 2) if total > 0 else 0,
            "message": f"正在补齐候选：{trade_date}" if trade_date else "正在补齐候选交易日",
        }
        _patch_job(run_id, safe)

    return callback


def _patch_job(run_id: str, patch: dict[str, Any]) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(run_id)
        if job:
            job.update(patch)


def _finish_job(run_id: str, status: str, message: str) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(run_id)
        if not job:
            return
        job["status"] = status
        job["finished_at"] = _utc_now_iso()
        job["message"] = message
        if status != "running":
            job["progress_pct"] = 100 if status == "succeeded" else job.get("progress_pct", 0)


def _copy_job(job: dict[str, Any]) -> dict[str, Any]:
    copied = dict(job)
    copied["params"] = dict(job.get("params") or {})
    for key in ("screen_run", "replay_run", "backtest"):
        value = job.get(key)
        copied[key] = dict(value) if isinstance(value, dict) else value
    return copied


def _compact_backtest(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "backtest_id": result.get("backtest_id"),
        "strategy": result.get("strategy"),
        "strategy_version": result.get("strategy_version"),
        "start": result.get("start"),
        "end": result.get("end"),
        "metrics": result.get("metrics") if isinstance(result.get("metrics"), dict) else {},
        "message": result.get("message"),
    }


def _failure_message(backtest: dict[str, Any], replay_run: dict[str, Any]) -> str:
    explicit = backtest.get("message") or replay_run.get("message")
    if explicit:
        return str(explicit)
    status = str(backtest.get("status") or replay_run.get("status") or "")
    if status == "insufficient_data":
        return "区间内日线数据不足，无法完成组合回测。请使用更长的历史区间。"
    if status:
        return f"组合回测失败：{status}"
    return "组合回测失败"


def _trim_jobs_locked() -> None:
    if len(_JOBS) <= _JOB_KEEP_LIMIT:
        return
    ordered = sorted(_JOBS.items(), key=lambda item: str(item[1].get("created_at") or ""))
    for job_id, job in ordered[: max(len(_JOBS) - _JOB_KEEP_LIMIT, 0)]:
        if job.get("status") != "running":
            _JOBS.pop(job_id, None)


def _date_text(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _parse_date_text(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
