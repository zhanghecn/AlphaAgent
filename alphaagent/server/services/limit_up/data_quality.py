"""Readiness gates and controlled minute backfill for limit-up evidence."""

from __future__ import annotations

import csv
import io
import threading
from datetime import date, datetime, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

from alphaagent.server.services import minute_provider_imports
from alphaagent.server.services.limit_up import data_quality_repository, history_engine
from alphaagent.server.services.limit_up.versions import LIVE_STRATEGY_VERSION

SHANGHAI = ZoneInfo("Asia/Shanghai")
DATA_QUALITY_VERSION = "limit-up-data-quality-v1"
RESEARCH_TRADE_DAY_TARGET = 500
EXECUTION_HISTORY_DAY_TARGET = 500
FORWARD_TRADE_DAY_TARGET = 60
MAX_BACKFILL_GAPS = 200
MINUTE_BACKFILL_PROVIDER = "tdx"
REMOTE_FAILURE_STATUSES = {"error", "partial", "unavailable", "unsupported_interval"}
_MINUTE_BACKFILL_LOCK = threading.Lock()


def get_limit_up_data_quality() -> dict[str, object]:
    counts = data_quality_repository.load_data_quality_counts(
        history_engine.HISTORY_STRATEGY_VERSION,
        LIVE_STRATEGY_VERSION,
    )
    return build_data_quality_report(counts)


def backfill_limit_up_event_minutes(
    *,
    max_gaps: int = 20,
    dry_run: bool = True,
) -> dict[str, object]:
    if max_gaps < 1 or max_gaps > MAX_BACKFILL_GAPS:
        raise ValueError(f"max_gaps must be between 1 and {MAX_BACKFILL_GAPS}")
    if not _MINUTE_BACKFILL_LOCK.acquire(blocking=False):
        return {
            "status": "busy",
            "scope": "limit_up_event_full_session",
            "message": "涨停事件分钟补数正在运行",
        }
    try:
        attempted_at = datetime.now(timezone.utc)
        gaps = data_quality_repository.list_missing_event_minute_pairs(
            max_gaps,
            provider=MINUTE_BACKFILL_PROVIDER,
            as_of=attempted_at,
        )
        if not gaps:
            return _no_retryable_gap_result()
        params = {
            "provider": MINUTE_BACKFILL_PROVIDER,
            "gap_csv_text": _event_gap_csv(gaps),
            "tail_entry_start": "09:15",
            "tail_entry_end": "15:00",
            "dry_run": dry_run,
            "max_gaps": len(gaps),
            "max_pages_per_symbol": 8,
            "timeout_seconds": 2,
        }
        try:
            result = minute_provider_imports.import_minute_bars_for_gaps(params)
        except Exception as exc:
            if not dry_run:
                data_quality_repository.record_minute_backfill_attempts(
                    _failed_attempts(gaps, str(exc)),
                    provider=MINUTE_BACKFILL_PROVIDER,
                    attempted_at=attempted_at,
                )
            raise
        attempt_counts = _record_backfill_result(
            gaps,
            result,
            dry_run=dry_run,
            attempted_at=attempted_at,
        )
        return {
            **result,
            **attempt_counts,
            "scope": "limit_up_event_full_session",
            "requested_gap_count": len(gaps),
            "dry_run": dry_run,
            "data_quality": get_limit_up_data_quality(),
        }
    finally:
        _MINUTE_BACKFILL_LOCK.release()


def minute_backfill_retry_at(attempted_at: datetime, attempt_count: int) -> datetime:
    return data_quality_repository.minute_backfill_retry_at(attempted_at, attempt_count)


def _record_backfill_result(
    gaps: list[Mapping[str, object]],
    result: Mapping[str, object],
    *,
    dry_run: bool,
    attempted_at: datetime,
) -> dict[str, int]:
    if dry_run:
        preview_covered = int(result.get("preview_covered_gap_count") or 0)
        return {
            "covered_gap_count": preview_covered,
            "empty_gap_count": 0,
            "error_gap_count": 0,
        }

    local_counts = data_quality_repository.load_event_minute_pair_bar_counts(gaps)
    remote_failed = str(result.get("status") or "") in REMOTE_FAILURE_STATUSES
    attempts: list[dict[str, object]] = []
    status_counts = {"covered": 0, "empty": 0, "error": 0}
    for gap in gaps:
        key = (
            str(gap.get("vt_symbol") or ""),
            date.fromisoformat(str(gap.get("trade_date") or "")[:10]),
        )
        rows_read = int(local_counts.get(key, 0) or 0)
        status = "covered" if rows_read > 0 else "error" if remote_failed else "empty"
        status_counts[status] += 1
        attempts.append(
            {
                "trade_date": key[1].isoformat(),
                "vt_symbol": key[0],
                "status": status,
                "last_rows_read": rows_read,
                "last_error": (
                    _provider_error_message(result, key[0])
                    if status == "error"
                    else None
                ),
            }
        )
    data_quality_repository.record_minute_backfill_attempts(
        attempts,
        provider=MINUTE_BACKFILL_PROVIDER,
        attempted_at=attempted_at,
    )
    return {
        "covered_gap_count": status_counts["covered"],
        "empty_gap_count": status_counts["empty"],
        "error_gap_count": status_counts["error"],
    }


def _failed_attempts(
    gaps: list[Mapping[str, object]],
    error: str,
) -> list[dict[str, object]]:
    return [
        {
            "trade_date": gap.get("trade_date"),
            "vt_symbol": gap.get("vt_symbol"),
            "status": "error",
            "last_rows_read": 0,
            "last_error": error,
        }
        for gap in gaps
    ]


def _provider_error_message(
    result: Mapping[str, object],
    vt_symbol: str | None = None,
) -> str:
    for key in ("message", "reason"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        matching = [str(item) for item in errors if vt_symbol and vt_symbol in str(item)]
        if matching:
            return "; ".join(matching[:5])
        return "; ".join(str(item) for item in errors[:5])
    note = str(result.get("note") or "").strip()
    if note:
        return note
    return f"provider_status={result.get('status') or 'error'}"


def _no_retryable_gap_result() -> dict[str, object]:
    quality = get_limit_up_data_quality()
    coverage = _section(quality, "minute_event_pair_coverage")
    attempts = _section(quality, "minute_backfill_attempts")
    missing = max(int(coverage.get("total") or 0) - int(coverage.get("covered") or 0), 0)
    cooling_down = int(attempts.get("cooling_down_pair_count") or 0)
    if missing == 0:
        status = "ready"
        message = "当前涨停事件分钟缺口已全部覆盖"
    elif cooling_down > 0:
        status = "cooling_down"
        message = f"当前没有可重试缺口，{cooling_down} 个缺口处于冷却"
    else:
        status = "empty"
        message = "当前没有可补的涨停事件分钟缺口"
    return {
        "status": status,
        "scope": "limit_up_event_full_session",
        "requested_gap_count": 0,
        "rows_read": 0,
        "rows_written": 0,
        "message": message,
        "data_quality": quality,
    }


def _event_gap_csv(gaps: list[Mapping[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["trade_date", "vt_symbol"])
    for gap in gaps:
        writer.writerow([gap.get("trade_date") or "", gap.get("vt_symbol") or ""])
    return buffer.getvalue()


def build_data_quality_report(
    raw: Mapping[str, object],
    *,
    as_of_date: date | None = None,
) -> dict[str, object]:
    history = _section(raw, "history")
    events = _section(raw, "events")
    memberships = _section(raw, "memberships")
    stock_minute = _section(raw, "stock_minute")
    sector_minute = _section(raw, "sector_minute")
    auction = _section(raw, "auction")
    tick_l2 = _section(raw, "tick_l2")
    forward = _section(raw, "forward")
    minute_backfill = _section(raw, "minute_backfill")

    event_fields = _event_field_coverage(events)
    minute_pairs = _minute_pair_coverage(stock_minute)
    gates = [
        _gate(
            "history_ledger",
            "点时历史账本",
            history,
            int(history.get("trade_days") or 0),
            RESEARCH_TRADE_DAY_TARGET,
            "trade_days",
            "point_in_time_daily_proxy",
            "继续保持至少500个交易日的无未来函数账本",
        ),
        _gate(
            "limit_event_path",
            "涨停事件路径",
            events,
            int(events.get("trade_days") or 0),
            EXECUTION_HISTORY_DAY_TARGET,
            "trade_days",
            "versioned_event_snapshot",
            "回补首次触板、开板、回封与最终状态的历史版本",
            quality_ready=min(event_fields.values(), default=0) >= 95,
        ),
        _gate(
            "historical_memberships",
            "逐日行业成员",
            memberships,
            int(memberships.get("point_in_time_trade_days") or 0),
            EXECUTION_HISTORY_DAY_TARGET,
            "trade_days",
            str(memberships.get("mode") or "unavailable"),
            "按交易日保存申万二级行业成员，禁止用当前行业覆盖历史",
        ),
        _gate(
            "stock_minute_path",
            "个股分钟路径",
            stock_minute,
            int(stock_minute.get("trade_days") or 0),
            EXECUTION_HISTORY_DAY_TARGET,
            "trade_days",
            "one_minute_bars",
            "优先补齐涨停事件股票的竞价、触板、开板与回封分钟线",
            quality_ready=float(minute_pairs["coverage_pct"]) >= 80,
        ),
        _gate(
            "auction_snapshots",
            "集合竞价快照",
            auction,
            int(auction.get("trade_days") or 0),
            EXECUTION_HISTORY_DAY_TARGET,
            "trade_days",
            str(auction.get("mode") or "not_collected"),
            "保存09:25价格、成交量、未匹配量和开盘状态",
            quality_ready=(
                int(auction.get("strict_trade_days") or 0)
                >= EXECUTION_HISTORY_DAY_TARGET
            ),
        ),
        _gate(
            "sector_minute_flow",
            "板块分钟资金",
            sector_minute,
            int(sector_minute.get("trade_days") or 0),
            EXECUTION_HISTORY_DAY_TARGET,
            "trade_days",
            str(sector_minute.get("mode") or "not_collected"),
            "保存板块净流入金额、比例、加速度和扩散宽度的时点快照",
        ),
        _gate(
            "tick_l2_queue",
            "Tick/L2封板队列",
            tick_l2,
            int(tick_l2.get("trade_days") or 0),
            FORWARD_TRADE_DAY_TARGET,
            "trade_days",
            str(tick_l2.get("mode") or "not_collected"),
            "接入买一队列、撤单速度、逐笔成交和排队位置",
        ),
        _gate(
            "forward_observation",
            "真实前向观察",
            forward,
            int(forward.get("eligible_trade_days") or 0),
            FORWARD_TRADE_DAY_TARGET,
            "trade_days",
            "saved_live_non_stale",
            "交易时段持续保存真实推荐并在D+1闭合结果",
        ),
    ]
    blockers = [gate for gate in gates if gate["required"] and gate["status"] != "ready"]
    history_gate = gates[0]
    return {
        "status": "ready" if not blockers else "collecting",
        "as_of_date": (as_of_date or datetime.now(SHANGHAI).date()).isoformat(),
        "version": DATA_QUALITY_VERSION,
        "history_strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "live_strategy_version": LIVE_STRATEGY_VERSION,
        "research_ledger_ready": history_gate["status"] == "ready",
        "simulation_eligible": not blockers,
        "targets": {
            "research_trade_days": RESEARCH_TRADE_DAY_TARGET,
            "execution_history_trade_days": EXECUTION_HISTORY_DAY_TARGET,
            "forward_trade_days": FORWARD_TRADE_DAY_TARGET,
        },
        "summary": {
            "required_gate_count": len(gates),
            "ready_gate_count": sum(gate["status"] == "ready" for gate in gates),
            "partial_gate_count": sum(gate["status"] == "partial" for gate in gates),
            "missing_gate_count": sum(gate["status"] == "missing" for gate in gates),
        },
        "gates": gates,
        "blocker_keys": [str(gate["key"]) for gate in blockers],
        "event_fields": event_fields,
        "minute_event_pair_coverage": minute_pairs,
        "minute_backfill_attempts": dict(minute_backfill),
        "source_counts": {key: dict(value) if isinstance(value, Mapping) else {} for key, value in raw.items()},
        "limitations": [
            "通过历史账本门槛只代表研究样本量足够，不代表盘口可成交。",
            "逐日板块成员、竞价、板块分钟资金和Tick/L2缺失时，模拟资格固定关闭。",
            "覆盖率只按真实落库数据计算，日线代理不会冒充竞价或排队证据。",
        ],
    }


def _gate(
    key: str,
    label: str,
    source: Mapping[str, object],
    current: int,
    target: int,
    unit: str,
    mode: str,
    next_action: str,
    *,
    quality_ready: bool = True,
) -> dict[str, object]:
    ready = current >= target and quality_ready
    status = "ready" if ready else "partial" if current > 0 else "missing"
    return {
        "key": key,
        "label": label,
        "status": status,
        "required": True,
        "current": current,
        "target": target,
        "unit": unit,
        "coverage_pct": round(min(100.0, current / target * 100), 4) if target else 0.0,
        "mode": mode,
        "start": source.get("start"),
        "end": source.get("end"),
        "next_action": next_action,
    }


def _event_field_coverage(events: Mapping[str, object]) -> dict[str, float]:
    rows = int(events.get("rows") or 0)
    sealed_rows = int(events.get("sealed_rows") or 0)
    return {
        "first_touch_pct": _percentage(events.get("first_touch_rows"), rows),
        "open_path_pct": _percentage(events.get("open_path_rows"), rows),
        "last_seal_pct": _percentage(events.get("last_seal_rows"), sealed_rows),
        "seal_amount_pct": _percentage(events.get("seal_amount_rows"), sealed_rows),
    }


def _minute_pair_coverage(stock_minute: Mapping[str, object]) -> dict[str, object]:
    total = int(stock_minute.get("event_pairs") or 0)
    covered = int(stock_minute.get("covered_event_pairs") or 0)
    return {
        "covered": covered,
        "total": total,
        "coverage_pct": _percentage(covered, total, digits=4),
    }


def _percentage(value: object, total: int, *, digits: int = 4) -> float:
    if total <= 0:
        return 0.0
    return round(int(value or 0) / total * 100, digits)


def _section(raw: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = raw.get(key)
    return value if isinstance(value, Mapping) else {}
