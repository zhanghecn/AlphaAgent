"""Background orchestration for the public quant research workflow."""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from alphaagent.market.boards import normalize_included_boards
from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.backtest.engine import candidate_trade_quality_report_from_quant_recommendations
from alphaagent.server.services.quant import screening
from alphaagent.server.services.quant.factors import STRATEGY_ID
from alphaagent.server.services.quant.strategy_registry import get_strategy


_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_LATEST_JOB_ID: str | None = None
_JOB_KEEP_LIMIT = 20
_COMPACT_CANDIDATE_QUALITY_LIST_KEYS = (
    "by_rank_bucket",
    "by_rank_limit",
    "by_daily_rank_window",
    "by_score_bucket",
    "by_setup_family",
    "by_market_phase",
    "by_timing_window",
    "by_timing_phase",
    "by_setup_x_timing",
    "by_month",
    "by_evaluation_window",
    "by_setup_family_rank_limit",
    "by_market_phase_rank_limit",
    "by_timing_window_rank_limit",
    "by_timing_phase_rank_limit",
    "by_setup_x_timing_rank_limit",
    "by_month_rank_limit",
    "by_month_timing_window_rank_limit",
    "by_month_timing_phase_rank_limit",
    "by_setup_month_timing_rank_limit",
    "by_setup_month_timing_phase_rank_limit",
    "by_evaluation_window_rank_limit",
    "by_d1_outcome",
    "by_exit_reason",
    "yearly",
    "daily_summaries",
    "best_samples",
    "worst_samples",
)


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
    candidate_limit: int = 20,
    strict_entry: bool = True,
    execution_model: str = "legacy_next_open",
    force_refresh: bool = False,
    persist_signal_details: bool = False,
    create_replay: bool = False,
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
        "candidate_limit": int(candidate_limit),
        "strict_entry": bool(strict_entry),
        "execution_model": execution_model,
        "force_refresh": bool(force_refresh),
        "persist_signal_details": bool(persist_signal_details),
        "create_replay": bool(create_replay),
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
        "message": "准备刷新候选并统计候选质量",
        "progress_current": 0,
        "progress_total": 0,
        "progress_pct": 0,
        "params": params,
        "screen_run": None,
        "replay_run": None,
        "replay_run_id": None,
        "backtest_id": None,
        "backtest": None,
        "candidate_trade_quality": None,
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
            persist_signal_details=bool(params.get("persist_signal_details")),
            create_replay=bool(params.get("create_replay")),
            progress=_screen_progress(run_id),
        )
        _patch_job(
            run_id,
            {
                "screen_run": screen_result,
                "replay_run": screen_result.get("replay_run"),
                "replay_run_id": screen_result.get("replay_run_id"),
                "stage": "candidate_quality",
                "message": "候选已生成，正在统计Top20独立买卖质量",
                "progress_current": 1,
                "progress_total": 1,
                "progress_pct": 90,
            },
        )
        if screen_result.get("status") not in {"ready", "empty"}:
            _finish_job(run_id, "failed", str(screen_result.get("message") or "候选生成失败"))
            return
        backtest_start = _parse_date_text(screen_result.get("start_date")) or start
        backtest_end = _parse_date_text(screen_result.get("end_date")) or end
        if backtest_start is None:
            backtest_start = date(2020, 1, 1)
        candidate_quality = candidate_trade_quality_report_from_quant_recommendations(
            strategy_id=str(params["strategy"]),
            strategy_version=str(screen_result.get("strategy_version") or ""),
            start=backtest_start,
            end=backtest_end or backtest_start,
            rank_limit=int(params["candidate_limit"]),
            sample_limit=500,
            min_entry_score=float(params["min_entry_score"]),
            strict_entry=bool(params["strict_entry"]),
            execution_model=str(params["execution_model"]),
            included_boards=tuple(params["included_boards"]),
        )
        _patch_job(
            run_id,
            {
                "candidate_trade_quality": _compact_candidate_trade_quality(candidate_quality),
                "progress_pct": 100,
                "stage": "candidate_quality",
                "message": "策略研究完成：主结果为Top20候选独立买卖质量",
            },
        )
        if candidate_quality.get("status") not in {"ready", "empty"}:
            _finish_job(run_id, "failed", str(candidate_quality.get("message") or "候选独立买卖质量统计失败"))
            return
        _finish_job(run_id, "succeeded", "策略研究完成：主结果为Top20候选独立买卖质量")
    except Exception as exc:
        _patch_job(run_id, {"error_type": exc.__class__.__name__, "error_detail": str(exc)})
        _finish_job(run_id, "failed", str(exc))


def _screen_progress(run_id: str) -> Callable[[dict[str, Any]], None]:
    def callback(patch: dict[str, Any]) -> None:
        current = int(patch.get("progress_current") or 0)
        total = int(patch.get("progress_total") or 0)
        trade_date = patch.get("trade_date")
        stage = str(patch.get("stage") or "screening")
        message = patch.get("message")
        safe = {
            "stage": stage,
            "progress_current": current,
            "progress_total": total,
            "progress_pct": round(min(current / total * 85, 85), 2) if total > 0 else 0,
            "message": str(message) if message else (f"正在补齐候选：{trade_date}" if trade_date else "正在补齐候选交易日"),
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
    for key in ("screen_run", "replay_run", "backtest", "candidate_trade_quality"):
        value = job.get(key)
        copied[key] = dict(value) if isinstance(value, dict) else value
    return copied


def _compact_candidate_trade_quality(result: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "status": result.get("status"),
        "start_date": result.get("start_date"),
        "end_date": result.get("end_date"),
        "strategy_id": result.get("strategy_id"),
        "strategy_version": result.get("strategy_version"),
        "rank_limit": result.get("rank_limit"),
        "sample_limit": result.get("sample_limit"),
        "entry_selection": result.get("entry_selection"),
        "entry_model": result.get("entry_model"),
        "primary_metric": result.get("primary_metric"),
        "method": result.get("method"),
        "summary": result.get("summary") if isinstance(result.get("summary"), dict) else {},
        "coverage": result.get("coverage") if isinstance(result.get("coverage"), dict) else {},
        "note": result.get("note"),
    }
    for key in _COMPACT_CANDIDATE_QUALITY_LIST_KEYS:
        value = result.get(key)
        if isinstance(value, list):
            payload[key] = value
    return payload


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
