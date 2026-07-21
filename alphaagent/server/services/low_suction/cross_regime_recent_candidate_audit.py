"""Separate recent legacy shadow rows from causal point-in-time replays."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

from .causal_leader_pullback import ROUND_TRIP_COST_PCT
from .causal_leader_pullback_forward import (
    FORWARD_CONTRACT_VERSION,
    FORWARD_IDENTITY_MODE,
    build_causal_forward_capture,
)
from .causal_leader_pullback_forward_repository import (
    evaluate_causal_candidate_outcomes,
    load_causal_replay_inputs,
)
from .forward_ma5_pullback import (
    FORWARD_MA5_CONTRACT_VERSION,
    ForwardMa5Capture,
)

AUDIT_VERSION = "low-suction-cross-regime-recent-candidate-audit-v1"
EXPECTED_LEGACY_CANDIDATE_ROWS = 356
SHANGHAI = ZoneInfo("Asia/Shanghai")
RECENT_REPLAY_PAIRS = (
    (date(2026, 7, 16), date(2026, 7, 17)),
    (date(2026, 7, 17), date(2026, 7, 20)),
)


@dataclass(frozen=True)
class RecentCausalReplay:
    source_trade_date: date
    signal_trade_date: date
    capture: ForwardMa5Capture
    observed_stock_bars: pd.DataFrame
    outcomes: pd.DataFrame


def run_cross_regime_recent_candidate_audit(
    *,
    as_of_date: date,
    evaluated_at: datetime | None = None,
    expected_legacy_candidate_rows: int | None = EXPECTED_LEGACY_CANDIDATE_ROWS,
) -> dict[str, object]:
    """Run two labeled historical replays without inserting forward evidence."""

    observed_at = evaluated_at or datetime.now(SHANGHAI)
    _require_aware(observed_at, "evaluated_at")
    legacy_scopes, legacy_candidates, legacy_outcomes = _load_legacy_shadow(
        as_of_date
    )
    if (
        expected_legacy_candidate_rows is not None
        and len(legacy_candidates) != expected_legacy_candidate_rows
    ):
        raise ValueError(
            "legacy shadow candidate count changed: "
            f"expected {expected_legacy_candidate_rows}, got {len(legacy_candidates)}"
        )

    replays: list[RecentCausalReplay] = []
    for source_trade_date, signal_trade_date in RECENT_REPLAY_PAIRS:
        if signal_trade_date > as_of_date:
            continue
        inputs = load_causal_replay_inputs(
            source_trade_date,
            signal_trade_date,
            evaluated_at=observed_at,
        )
        capture = build_causal_forward_capture(inputs)
        candidate_frame = pd.DataFrame([asdict_row(row) for row in capture.rows])
        outcomes, stock_bars = evaluate_causal_candidate_outcomes(
            candidate_frame,
            as_of_date=as_of_date,
        )
        replays.append(
            RecentCausalReplay(
                source_trade_date=source_trade_date,
                signal_trade_date=signal_trade_date,
                capture=capture,
                observed_stock_bars=stock_bars,
                outcomes=outcomes,
            )
        )
    return build_cross_regime_recent_candidate_audit(
        legacy_scopes=legacy_scopes,
        legacy_candidates=legacy_candidates,
        legacy_outcomes=legacy_outcomes,
        causal_replays=tuple(replays),
        as_of_date=as_of_date,
        evaluated_at=observed_at,
    )


def build_cross_regime_recent_candidate_audit(
    *,
    legacy_scopes: pd.DataFrame,
    legacy_candidates: pd.DataFrame,
    legacy_outcomes: pd.DataFrame,
    causal_replays: Sequence[RecentCausalReplay],
    as_of_date: date,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Build disjoint ledgers and reject duplicate causal candidate identities."""

    _require_aware(evaluated_at, "evaluated_at")
    if evaluated_at.astimezone(SHANGHAI).date() < as_of_date:
        raise ValueError("evaluated_at cannot precede as_of_date")
    legacy = _legacy_section(
        legacy_scopes,
        legacy_candidates,
        legacy_outcomes,
    )
    replay_sections = [_causal_replay_section(replay, as_of_date) for replay in causal_replays]
    individual_cases = [
        case
        for section in replay_sections
        for case in section["individual_cases"]
    ]
    identities = [
        (case["signal_trade_date"], case["vt_symbol"])
        for case in individual_cases
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("causal replay candidate identity must be unique")

    funnel: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for section in replay_sections:
        funnel.update(section["signal_funnel"])
        reasons.update(section["rejection_reason_counts"])
    return {
        "audit_version": AUDIT_VERSION,
        "as_of_date": as_of_date.isoformat(),
        "evaluated_at": evaluated_at.astimezone(SHANGHAI).isoformat(),
        "legacy_shadow": legacy,
        "causal_replay": {
            "contract_version": FORWARD_CONTRACT_VERSION,
            "identity_mode": FORWARD_IDENTITY_MODE,
            "evidence_mode": "retrospective_strict_d1_point_in_time_replay",
            "forward_sample": False,
            "replay_dates": [
                {
                    "source_trade_date": section["source_trade_date"],
                    "signal_trade_date": section["signal_trade_date"],
                    "scope_status": section["scope_status"],
                    "scope_complete": section["scope_complete"],
                    "active_concept_count": section["active_concept_count"],
                    "prior_top3_count": section["prior_top3_count"],
                    "candidate_rows": section["candidate_rows"],
                    "signal_rows": section["signal_rows"],
                }
                for section in replay_sections
            ],
            "candidate_rows": len(individual_cases),
            "signal_rows": sum(
                bool(case["signal_eligible"]) for case in individual_cases
            ),
            "signal_funnel": dict(sorted(funnel.items())),
            "rejection_reason_counts": dict(sorted(reasons.items())),
            "individual_cases": individual_cases,
            "formal_metrics": None,
        },
        "formal_metrics": None,
        "boundaries": [
            "legacy_shadow and causal_replay are separate populations",
            "causal replay rows are never inserted into the V2 forward tables",
            "retrospective D-1 snapshots do not become natural forward samples",
        ],
    }


def render_recent_candidate_audit_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_recent_candidate_audit_markdown(report: Mapping[str, Any]) -> str:
    legacy = _mapping(report.get("legacy_shadow"))
    causal = _mapping(report.get("causal_replay"))
    lines = [
        "# AlphaAgent 近期低吸候选逐股审计",
        "",
        f"审计版本：`{report.get('audit_version')}`；截至 `{report.get('as_of_date')}`。",
        "正式胜率和复利：`null`。",
        "",
        "## 旧 MA5 前向影子",
        "",
        f"- 合同：`{legacy.get('contract_version')}`。",
        f"- 候选/信号/结果：`{legacy.get('candidate_rows', 0)}` / "
        f"`{legacy.get('signal_rows', 0)}` / `{legacy.get('outcome_rows', 0)}`。",
        "",
        "## 因果点时回放",
        "",
        "- `forward_sample=false`，本节不进入自然前向胜率。",
        f"- 候选/信号：`{causal.get('candidate_rows', 0)}` / "
        f"`{causal.get('signal_rows', 0)}`。",
        "",
        "| 来源日 | 信号日 | 状态 | 活跃概念 | Top3 | 候选 | 信号 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    replay_dates = causal.get("replay_dates")
    if isinstance(replay_dates, Sequence) and not isinstance(
        replay_dates, (str, bytes)
    ):
        for replay_date in replay_dates:
            row = _mapping(replay_date)
            lines.append(
                f"| {row.get('source_trade_date')} | {row.get('signal_trade_date')} | "
                f"`{row.get('scope_status')}` | {row.get('active_concept_count', 0)} | "
                f"{row.get('prior_top3_count', 0)} | {row.get('candidate_rows', 0)} | "
                f"{row.get('signal_rows', 0)} |"
            )
    lines.extend(
        [
        "",
        "| 日期 | 股票 | 概念 | 排名 | 阶段 | 波次 | 支撑 | 决策 | D+1净收益 |",
        "| --- | --- | --- | ---: | --- | ---: | --- | --- | ---: |",
        ]
    )
    cases = causal.get("individual_cases")
    if isinstance(cases, Sequence) and not isinstance(cases, (str, bytes)):
        for case in cases:
            row = _mapping(case)
            d1_return = row.get("d1_net_return_pct")
            lines.append(
                f"| {row.get('signal_trade_date')} | {row.get('stock_name')} "
                f"(`{row.get('vt_symbol')}`) | {row.get('concept_name')} | "
                f"{row.get('rank')} | `{row.get('market_phase')}` | "
                f"{row.get('wave_number')} | `{row.get('support_line')}` | "
                f"`{row.get('decision_reason')}` | "
                f"{_format_pct(d1_return)} |"
            )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "旧影子合同与当前因果算法不是同一分母，不合并计算胜率。",
            "2026-07-17/20 只按历史可见字段重放，不能冒充当日自然冻结样本。",
            "",
        ]
    )
    return "\n".join(lines)


def archive_recent_candidate_audit(
    report: Mapping[str, Any],
    output: Path,
) -> dict[str, str]:
    """Write deterministic JSON/Markdown once and reject content changes."""

    json_payload = render_recent_candidate_audit_json(report).encode("utf-8")
    markdown_path = output.with_suffix(".md")
    markdown_payload = render_recent_candidate_audit_markdown(report).encode("utf-8")
    payloads = ((output, json_payload), (markdown_path, markdown_payload))
    for path, payload in payloads:
        if path.exists() and path.read_bytes() != payload:
            raise FileExistsError(f"refusing to overwrite {path} with different content")
    for path, payload in payloads:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return {
        "json_path": str(output),
        "markdown_path": str(markdown_path),
        "json_sha256": hashlib.sha256(json_payload).hexdigest(),
        "markdown_sha256": hashlib.sha256(markdown_payload).hexdigest(),
    }


def _load_legacy_shadow(
    as_of_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    engine = get_engine()
    schema.ensure_schema_once(engine)
    scopes = schema.low_suction_forward_ma5_scopes
    candidates = schema.low_suction_forward_ma5_candidates
    outcomes = schema.low_suction_forward_ma5_outcomes
    with session_scope() as session:
        scope_rows = session.execute(
            select(scopes)
            .where(
                scopes.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                scopes.c.signal_trade_date <= as_of_date,
            )
            .order_by(scopes.c.signal_trade_date, scopes.c.identity_mode)
        ).mappings().all()
        candidate_rows = session.execute(
            select(candidates)
            .where(
                candidates.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                candidates.c.signal_trade_date <= as_of_date,
            )
            .order_by(
                candidates.c.signal_trade_date,
                candidates.c.identity_mode,
                candidates.c.vt_symbol,
            )
        ).mappings().all()
        outcome_rows = session.execute(
            select(outcomes)
            .where(
                outcomes.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                outcomes.c.signal_trade_date <= as_of_date,
            )
            .order_by(
                outcomes.c.signal_trade_date,
                outcomes.c.identity_mode,
                outcomes.c.vt_symbol,
            )
        ).mappings().all()
    return (
        pd.DataFrame(scope_rows),
        pd.DataFrame(candidate_rows),
        pd.DataFrame(outcome_rows),
    )


def _legacy_section(
    scopes: pd.DataFrame,
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> dict[str, object]:
    dates = sorted(
        {
            _date_text(value)
            for value in candidates.get("signal_trade_date", pd.Series(dtype=object))
        }
    )
    modes = sorted(
        set(candidates.get("identity_mode", pd.Series(dtype=str)).dropna().astype(str))
    )
    signal_rows = int(
        candidates.get("signal_eligible", pd.Series(dtype=bool)).astype(bool).sum()
    )
    return {
        "contract_version": FORWARD_MA5_CONTRACT_VERSION,
        "forward_sample": True,
        "scope_rows": int(len(scopes)),
        "candidate_rows": int(len(candidates)),
        "signal_rows": signal_rows,
        "outcome_rows": int(len(outcomes)),
        "signal_trade_dates": dates,
        "identity_modes": modes,
        "formal_metrics": None,
    }


def _causal_replay_section(
    replay: RecentCausalReplay,
    as_of_date: date,
) -> dict[str, object]:
    if replay.capture.source_trade_date != replay.source_trade_date:
        raise ValueError("causal replay source date does not match its capture")
    if replay.capture.signal_trade_date != replay.signal_trade_date:
        raise ValueError("causal replay signal date does not match its capture")
    identities = [(row.signal_trade_date, row.vt_symbol) for row in replay.capture.rows]
    if len(identities) != len(set(identities)):
        raise ValueError("causal replay candidate identity must be unique")
    cases = [
        _individual_case(row, replay.observed_stock_bars, replay.outcomes, as_of_date)
        for row in replay.capture.rows
    ]
    scope = replay.capture.scopes[0]
    raw_funnel = scope.raw.get("signal_funnel")
    funnel = (
        {str(key): int(value) for key, value in raw_funnel.items()}
        if isinstance(raw_funnel, Mapping)
        else {}
    )
    reasons = Counter(case["decision_reason"] for case in cases)
    return {
        "source_trade_date": replay.source_trade_date.isoformat(),
        "signal_trade_date": replay.signal_trade_date.isoformat(),
        "scope_status": scope.status,
        "scope_complete": bool(scope.complete),
        "active_concept_count": int(scope.active_concept_count),
        "prior_top3_count": int(scope.prior_top3_count),
        "candidate_rows": len(cases),
        "signal_rows": sum(bool(case["signal_eligible"]) for case in cases),
        "signal_funnel": funnel,
        "rejection_reason_counts": dict(sorted(reasons.items())),
        "individual_cases": cases,
    }


def _individual_case(
    row,
    observed_stock_bars: pd.DataFrame,
    outcomes: pd.DataFrame,
    as_of_date: date,
) -> dict[str, object]:
    signal = row.raw.get("signal") if isinstance(row.raw, Mapping) else None
    if not isinstance(signal, Mapping):
        raise ValueError("causal replay candidate is missing its frozen signal")
    signal_date = row.signal_trade_date
    symbol_bars = _prepared_observed_bars(
        observed_stock_bars,
        vt_symbol=row.vt_symbol,
        start=signal_date,
        end=as_of_date,
    )
    later = symbol_bars.loc[symbol_bars["trade_date"].gt(pd.Timestamp(signal_date))]
    d1 = later.iloc[0] if not later.empty else None
    entry_price = _finite_or_none(signal.get("signal_close"))
    d1_close = _finite_or_none(d1.get("close_price")) if d1 is not None else None
    d1_net_return = (
        (d1_close / entry_price - 1.0) * 100.0 - ROUND_TRIP_COST_PCT
        if entry_price and d1_close is not None
        else None
    )
    outcome = _matching_outcome(outcomes, signal_date, row.vt_symbol)
    direction = str(signal.get("active_direction") or row.market_timing_direction or "UNKNOWN")
    danger = str(signal.get("danger_state") or row.market_timing_danger_state or "UNKNOWN")
    market_phase = str(signal.get("market_phase") or "UNKNOWN")
    return {
        "source_trade_date": row.source_trade_date.isoformat(),
        "signal_trade_date": signal_date.isoformat(),
        "campaign_id": str(signal.get("campaign_id") or ""),
        "sector_id": row.sector_id,
        "concept_name": row.sector_name,
        "vt_symbol": row.vt_symbol,
        "stock_name": row.stock_name,
        "rank": int(row.rank),
        "market_direction": direction,
        "danger_state": danger,
        "market_phase": market_phase,
        "wave_number": int(row.current_wave_number),
        "support_line": row.support_line,
        "support_price": _finite_or_none(row.support_price),
        "support_gap_low_pct": _finite_or_none(row.line_distance_low_pct),
        "support_gap_close_pct": _finite_or_none(row.line_distance_close_pct),
        "reference_peak_date": row.reference_peak_date.isoformat(),
        "reference_peak_price": _finite_or_none(row.reference_peak_price),
        "gates": {
            "gold_direction": direction == "GOLD",
            "normal_danger": danger == "NORMAL",
            "dynamic_top3": bool(signal.get("dynamic_top3")),
            "concept_main_rise_intact": bool(row.concept_main_rise_intact),
            "stock_structure_intact": bool(row.stock_structure_intact),
            "support_reclaimed": bool(
                entry_price is not None
                and row.support_price is not None
                and entry_price >= float(row.support_price)
            ),
            "support_relevance": bool(row.signal_eligible),
        },
        "signal_eligible": bool(row.signal_eligible),
        "decision_reason": row.decision_reason,
        "d1_outcome_observable": d1 is not None,
        "d1_trade_date": _date_text(d1.get("trade_date")) if d1 is not None else None,
        "d1_close": d1_close,
        "d1_net_return_pct": d1_net_return,
        "d1_won": d1_net_return > 0 if d1_net_return is not None else None,
        "structural_outcome_observable": bool(outcome.get("terminal")) if outcome else False,
        "structural_status": outcome.get("status") if outcome else None,
        "structural_exit_date": _optional_date_text(outcome.get("exit_date")) if outcome else None,
        "structural_exit_reason": outcome.get("exit_reason") if outcome else None,
        "structural_net_return_pct": _finite_or_none(outcome.get("net_return_pct")) if outcome else None,
    }


def _prepared_observed_bars(
    bars: pd.DataFrame,
    *,
    vt_symbol: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    if bars.empty or not {"vt_symbol", "trade_date", "close_price"}.issubset(bars.columns):
        return pd.DataFrame(columns=["vt_symbol", "trade_date", "close_price"])
    frame = bars.loc[bars["vt_symbol"].astype(str).eq(vt_symbol)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    return frame.loc[
        frame["trade_date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ].sort_values("trade_date", kind="stable")


def _matching_outcome(
    outcomes: pd.DataFrame,
    signal_trade_date: date,
    vt_symbol: str,
) -> dict[str, object] | None:
    if outcomes.empty or not {"signal_trade_date", "vt_symbol"}.issubset(outcomes.columns):
        return None
    signal_dates = pd.to_datetime(outcomes["signal_trade_date"], errors="raise").dt.date
    matches = outcomes.loc[
        signal_dates.eq(signal_trade_date)
        & outcomes["vt_symbol"].astype(str).eq(vt_symbol)
    ]
    if len(matches) > 1:
        raise ValueError("causal replay outcome identity must be unique")
    return matches.iloc[0].to_dict() if len(matches) == 1 else None


def asdict_row(row: object) -> dict[str, object]:
    if not hasattr(row, "__dataclass_fields__"):
        raise TypeError("causal replay candidate must be a dataclass row")
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _format_pct(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:+.4f}%"


def _date_text(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()


def _optional_date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return _date_text(value)


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
