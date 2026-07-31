"""Read-only grid study for limit-up recognition-count windows and ranges."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up import (
    cash_backtest,
    first_board_stock_gene_research,
    history_engine,
    history_repository,
    quality_no_trade_reverse,
    quality_opportunity_reverse,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    performance_summary,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


STUDY_VERSION = "limit-up-recognition-gate-window-grid-v1"
WINDOW_LABELS = {42: "2m_42_sessions", 63: "3m_63_sessions", 126: "6m_126_sessions"}
COUNT_BOUNDS = tuple(range(1, 11))
BASELINE_KEY = (126, 2, 6)
HIGH_RETURN_PCT = 5.0
MINIMUM_STRICT_CLOSED_COUNT = 15
STRICT_TRAINING_SESSIONS = 252
STRICT_CALIBRATION_SESSIONS = 63
STRICT_TEST_SESSIONS = 63
STRICT_HOLDOUT_SESSIONS = 120
BOOTSTRAP_DRAWS = 2_000
BOOTSTRAP_SEED = 20260730
DESCRIPTIVE_BATCHES = (
    ("2025_06_12", date(2025, 6, 27), date(2025, 12, 31)),
    ("2026_01_02", date(2026, 1, 1), date(2026, 2, 28)),
    ("2026_03_07", date(2026, 3, 1), date(2026, 7, 31)),
)


@dataclass(frozen=True)
class GridVariant:
    """One pre-registered recognition-count interval."""

    window_sessions: int
    lower: int
    upper: int

    @property
    def name(self) -> str:
        return (
            f"window_{self.window_sessions}_count_{self.lower}_to_{self.upper}"
        )

    @property
    def count_field(self) -> str:
        return f"prior_limit_count_{self.window_sessions}"

    @property
    def window_label(self) -> str:
        return WINDOW_LABELS[self.window_sessions]


GRID_VARIANTS = tuple(
    GridVariant(window_sessions, lower, upper)
    for window_sessions in sorted(WINDOW_LABELS)
    for lower in COUNT_BOUNDS
    for upper in COUNT_BOUNDS
    if lower <= upper
)
BASELINE_VARIANT = next(
    variant
    for variant in GRID_VARIANTS
    if (variant.window_sessions, variant.lower, variant.upper) == BASELINE_KEY
)


def attach_recomputed_limit_counts(
    frame: pd.DataFrame,
    feature_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Join strictly-prior count evidence and make source drift explicit."""

    if frame.empty:
        return frame.copy(), _count_audit(0, 0, 0, [])
    required_fields = ("trade_date", "vt_symbol", *_count_fields())
    missing = [field for field in required_fields if field not in feature_frame]
    if missing:
        raise ValueError(f"limit count feature fields unavailable: {', '.join(missing)}")

    count_lookup: dict[tuple[date, str], dict[str, int]] = {}
    for row in feature_frame.loc[:, required_fields].to_dict("records"):
        identity = _identity(row)
        if identity is None:
            continue
        if identity in count_lookup:
            raise ValueError(f"duplicate daily feature identity: {identity}")
        counts = {
            field: _optional_integer(row.get(field))
            for field in _count_fields()
        }
        if any(value is None for value in counts.values()):
            continue
        count_lookup[identity] = {field: int(value) for field, value in counts.items()}

    records: list[dict[str, object]] = []
    matched_count = 0
    mismatched_count = 0
    missing_count = 0
    examples: list[dict[str, object]] = []
    for raw_row in frame.to_dict("records"):
        row = dict(raw_row)
        identity = _identity(row)
        stored_126 = _optional_integer(row.get("prior_limit_count_126"))
        counts = count_lookup.get(identity) if identity is not None else None
        row["frozen_prior_limit_count_126"] = stored_126
        if counts is None:
            missing_count += 1
            row["count_evidence_verified"] = False
            for field in _count_fields():
                row[field] = None
            if len(examples) < 10:
                examples.append(
                    {
                        "status": "missing",
                        "signal_date": identity[0].isoformat() if identity else None,
                        "vt_symbol": identity[1] if identity else None,
                    }
                )
            records.append(row)
            continue
        for field, value in counts.items():
            row[field] = value
        verified = stored_126 is not None and stored_126 == counts["prior_limit_count_126"]
        row["count_evidence_verified"] = verified
        if verified:
            matched_count += 1
        else:
            mismatched_count += 1
            if len(examples) < 10:
                examples.append(
                    {
                        "status": "mismatch",
                        "signal_date": identity[0].isoformat() if identity else None,
                        "vt_symbol": identity[1] if identity else None,
                        "frozen_prior_limit_count_126": stored_126,
                        "recomputed_prior_limit_count_126": counts[
                            "prior_limit_count_126"
                        ],
                    }
                )
        records.append(row)
    return pd.DataFrame.from_records(records), _count_audit(
        matched_count,
        mismatched_count,
        missing_count,
        examples,
    )


def variant_mask(frame: pd.DataFrame, variant: GridVariant) -> pd.Series:
    """Return membership from decision-time fields only."""

    counts = _numeric_series(frame, variant.count_field)
    return (
        _boolean_series(frame, "profitability_gate_passed")
        & _boolean_series(frame, "count_evidence_verified")
        & counts.between(variant.lower, variant.upper)
    )


def select_calibration_variant(reports: Sequence[Mapping[str, object]]) -> str | None:
    """Choose only from training and calibration metrics, never OOS/holdout."""

    eligible: list[Mapping[str, object]] = []
    for report in reports:
        strict = _mapping(report.get("strict"))
        training = _mapping(strict.get("training"))
        calibration = _mapping(strict.get("calibration"))
        if _selection_phase_ready(training) and _selection_phase_ready(calibration):
            eligible.append(report)
    if not eligible:
        return None
    selected = max(eligible, key=_calibration_sort_key)
    return str(selected.get("name") or "") or None


def date_block_bootstrap_delta(
    baseline: pd.DataFrame,
    variant: pd.DataFrame,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Bootstrap the mean-return delta by complete signal-date blocks."""

    if draws <= 0:
        raise ValueError("bootstrap draws must be positive")
    baseline_by_date = _returns_by_date(baseline)
    variant_by_date = _returns_by_date(variant)
    dates = sorted(set(baseline_by_date) | set(variant_by_date))
    if not dates or not baseline_by_date or not variant_by_date:
        return {
            "draws": draws,
            "signal_date_count": len(dates),
            "mean_delta_pct": None,
            "mean_delta_lower_95": None,
            "mean_delta_upper_95": None,
        }
    random = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(draws):
        sampled_dates = random.choice(dates, size=len(dates), replace=True)
        baseline_values = [
            value
            for sample_date in sampled_dates
            for value in baseline_by_date.get(sample_date, ())
        ]
        variant_values = [
            value
            for sample_date in sampled_dates
            for value in variant_by_date.get(sample_date, ())
        ]
        if baseline_values and variant_values:
            values.append(float(np.mean(variant_values) - np.mean(baseline_values)))
    if not values:
        return {
            "draws": draws,
            "signal_date_count": len(dates),
            "mean_delta_pct": None,
            "mean_delta_lower_95": None,
            "mean_delta_upper_95": None,
        }
    return {
        "draws": draws,
        "signal_date_count": len(dates),
        "mean_delta_pct": round(float(np.mean(values)), 4),
        "mean_delta_lower_95": round(float(np.quantile(values, 0.025)), 4),
        "mean_delta_upper_95": round(float(np.quantile(values, 0.975)), 4),
    }


def evaluate_window_grid(
    frame: pd.DataFrame,
    *,
    trade_dates: Sequence[date],
    official_daily_bars: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Evaluate every registered interval without changing the formal contract."""

    valid_mother = frame.loc[
        _boolean_series(frame, "profitability_gate_passed")
        & _boolean_series(frame, "count_evidence_verified")
    ].copy()
    strict_plan = build_strict_validation_plan(valid_mother, trade_dates=trade_dates)
    reports = [
        _variant_report(valid_mother, variant, strict_plan)
        for variant in GRID_VARIANTS
    ]
    reports_by_name = {str(report["name"]): report for report in reports}
    baseline = reports_by_name[BASELINE_VARIANT.name]
    selected_name = (
        select_calibration_variant(reports)
        if strict_plan["status"] == "ready"
        else None
    )
    strict_result = _strict_result(
        selected_name,
        reports_by_name,
        baseline,
        strict_plan,
        valid_mother,
        trade_dates,
        official_daily_bars,
    )
    integrity = _input_integrity(frame)
    status = str(strict_result["status"])
    if integrity["status"] != "ready":
        status = "INPUT_DRIFT_REJECTED"
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "analysis_layer": "ab_base_recognition_gate_only",
        "formal_contract_changed": False,
        "grid": {
            "window_sessions": sorted(WINDOW_LABELS),
            "window_labels": dict(WINDOW_LABELS),
            "count_bounds": list(COUNT_BOUNDS),
            "variant_count": len(GRID_VARIANTS),
            "baseline": _variant_descriptor(BASELINE_VARIANT),
        },
        "thresholds": {
            "high_return_pct": HIGH_RETURN_PCT,
            "minimum_strict_closed_count": MINIMUM_STRICT_CLOSED_COUNT,
        },
        "input_integrity": integrity,
        "mother_pool": _signal_summary(valid_mother, valid_mother),
        "strict_validation_plan": strict_plan,
        "baseline": baseline,
        "descriptive_leaders": _descriptive_leaders(reports),
        "selected_by_calibration": selected_name,
        "strict_result": strict_result,
        "decision": _research_decision(status, strict_plan),
        "variants": reports_by_name,
    }


def build_strict_validation_plan(
    frame: pd.DataFrame,
    *,
    trade_dates: Sequence[date],
) -> dict[str, object]:
    """Create fixed chronological phases without shortening them after inspection."""

    signal_dates = _date_series(frame, "trade_date").dropna()
    if signal_dates.empty:
        return _strict_plan_unavailable(0, None, None)
    first_signal = min(signal_dates)
    last_signal = max(signal_dates)
    calendar = sorted(
        {
            value
            for value in (_as_date(item) for item in trade_dates)
            if value is not None and first_signal <= value <= last_signal
        }
    )
    required = (
        STRICT_TRAINING_SESSIONS
        + STRICT_CALIBRATION_SESSIONS
        + STRICT_TEST_SESSIONS
        + STRICT_HOLDOUT_SESSIONS
    )
    if len(calendar) < required:
        return _strict_plan_unavailable(len(calendar), first_signal, last_signal)

    calibration_start_index = STRICT_TRAINING_SESSIONS
    test_start_index = calibration_start_index + STRICT_CALIBRATION_SESSIONS
    holdout_start_index = max(
        len(calendar) - STRICT_HOLDOUT_SESSIONS,
        test_start_index + STRICT_TEST_SESSIONS,
    )
    test_phases: list[dict[str, object]] = []
    sequence = 1
    for start_index in range(test_start_index, holdout_start_index, STRICT_TEST_SESSIONS):
        end_index = min(start_index + STRICT_TEST_SESSIONS, holdout_start_index) - 1
        test_phases.append(
            {
                "name": f"oos_{sequence}",
                "start": calendar[start_index],
                "end": calendar[end_index],
                "mature_before": (
                    calendar[end_index + 1]
                    if end_index + 1 < len(calendar)
                    else None
                ),
            }
        )
        sequence += 1
    test_start = calendar[test_start_index]
    return {
        "status": "ready",
        "candidate_session_count": len(calendar),
        "required_session_count": required,
        "candidate_start": first_signal.isoformat(),
        "candidate_end": last_signal.isoformat(),
        "training": {
            "start": calendar[0],
            "end": calendar[calibration_start_index - 1],
            "mature_before": calendar[calibration_start_index],
        },
        "calibration": {
            "start": calendar[calibration_start_index],
            "end": calendar[test_start_index - 1],
            "mature_before": test_start,
        },
        "oos": test_phases,
        "holdout": {
            "start": calendar[holdout_start_index],
            "end": calendar[-1],
            "mature_before": None,
        },
    }


def run_research(*, start: date, end: date) -> dict[str, object]:
    """Load frozen data, rebuild count features, and evaluate the read-only grid."""

    days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        compact=False,
    )
    if not days:
        raise ValueError("persisted limit-up history is unavailable")
    orders = scheduled_execution.extract_scheduled_orders(days)
    enriched_orders = (
        first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
            days,
            orders,
        )
    )
    symbols = sorted(
        {
            str(order.get("vt_symbol") or "").strip()
            for order in enriched_orders
            if str(order.get("vt_symbol") or "").strip()
        }
    )
    history_start = _as_date(days[0].get("trade_date"))
    if history_start is None:
        raise ValueError("persisted history has no valid first date")
    daily_bars = history_repository.load_limit_gene_daily_bars(
        symbols,
        history_start,
        end,
    )
    closed_trades = quality_no_trade_reverse.build_official_closed_trade_evidence(
        enriched_orders,
        daily_bars,
        start=start,
        end=end,
    )
    outcome_frame = quality_opportunity_reverse.build_opportunity_reverse_frame(
        enriched_orders,
        closed_trades,
    )
    feature_frame = history_engine.build_daily_feature_frame(daily_bars)
    counted_frame, count_audit = attach_recomputed_limit_counts(
        outcome_frame,
        feature_frame,
    )
    trade_dates = [
        parsed
        for day in days
        if (parsed := _as_date(day.get("trade_date"))) is not None
    ]
    result = evaluate_window_grid(
        counted_frame,
        trade_dates=trade_dates,
        official_daily_bars=daily_bars,
    )
    result.update(
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "history_start": history_start.isoformat(),
            "history_day_count": len(days),
            "scheduled_order_count": len(enriched_orders),
            "closed_candidate_count": len(counted_frame),
            "daily_bar_count": len(daily_bars),
            "feature_row_count": len(feature_frame),
            "count_reconciliation": count_audit,
            "input_fingerprint": _input_fingerprint(counted_frame),
        }
    )
    return result


def render_markdown(result: Mapping[str, object]) -> str:
    """Render a compact decision report while keeping all 165 rows in JSON."""

    integrity = _mapping(result.get("input_integrity"))
    count_audit = _mapping(result.get("count_reconciliation"))
    baseline = _mapping(_mapping(result.get("baseline")).get("full"))
    strict_plan = _mapping(result.get("strict_validation_plan"))
    strict_result = _mapping(result.get("strict_result"))
    decision = _mapping(result.get("decision"))
    lines = [
        "# Recognition Gate Window Grid Research",
        "",
        "## Boundary",
        "",
        f"- 状态：`{str(result.get('status') or 'unavailable')}`。",
        "- 本研究仅替换 A+B 基座的过去封板次数窗口与闭区间；正式 `limit-up-core-abc-v2`、C、实时推荐和账户均未修改。",
        "- 42/63/126 代表每只股票的交易日行数，不是自然月；当前信号日不进入自己的计数。",
        "- 全历史和已见分批排序都只是反事实描述。只有固定严格时序和两仓验收同时通过，才可能作为后续自然前向的 shadow 候选。",
        "",
        "## Input Coverage",
        "",
        f"- 回放日：{_integer(result.get('history_day_count'))}；调度候选：{_integer(result.get('scheduled_order_count'))}；闭合候选：{_integer(result.get('closed_candidate_count'))}。",
        f"- 原计数核对：匹配 {_integer(count_audit.get('matched_count'))}，不匹配 {_integer(count_audit.get('mismatched_count'))}，缺失 {_integer(count_audit.get('missing_count'))}。",
        f"- 输入完整性：`{str(integrity.get('status') or 'unavailable')}`；输入指纹：`{str(result.get('input_fingerprint') or '-')}`。",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
        "",
        "## Baseline",
        "",
        "| 方案 | 闭合 | 胜率 | 均值 | 日等权复利 | 最大回撤 | 硬亏率 | 高收益日最高票捕获 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        _summary_table_row("6m/126日 2-6（当前A+B对照）", baseline),
        "",
        "## Descriptive Leaders",
        "",
        "| 窗口 | 全历史描述性最高组合 | 闭合 | 胜率 | 均值 | 日等权复利 | 3-7月胜率/均值 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    leaders = _mapping(result.get("descriptive_leaders"))
    variants = _mapping(result.get("variants"))
    for sessions in sorted(WINDOW_LABELS):
        leader = _mapping(leaders.get(str(sessions)))
        report = _mapping(variants.get(str(leader.get("name") or "")))
        full = _mapping(report.get("full"))
        recent = _mapping(_mapping(report.get("descriptive_batches")).get("2026_03_07"))
        range_text = (
            f"{_integer(leader.get('lower'))}-{_integer(leader.get('upper'))}"
            if leader
            else "无足够样本"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    WINDOW_LABELS[sessions],
                    range_text,
                    str(_integer(full.get("closed_count"))),
                    _pct(full.get("win_rate_pct")),
                    _signed_pct(full.get("average_return_pct")),
                    _signed_pct(full.get("daily_equal_weight_compounded_pct")),
                    f"{_pct(recent.get('win_rate_pct'))}/{_signed_pct(recent.get('average_return_pct'))}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
        "## Strict Validation",
            "",
            f"- 可用候选交易日：{_integer(strict_plan.get('candidate_session_count'))}/"
            f"{_integer(strict_plan.get('required_session_count'))}；严格状态：`{str(strict_plan.get('status') or 'unavailable')}`。",
        f"- calibration 选中：`{str(result.get('selected_by_calibration') or 'none')}`；验收状态：`{str(strict_result.get('status') or 'unavailable')}`。",
        f"- 当前结论：`{str(decision.get('formal_action') or 'NO_DECISION')}`；{str(decision.get('reason') or '-')}。",
        ]
    )
    selected = _mapping(strict_result.get("selected"))
    if selected:
        lines.extend(
            [
                "",
                "| 阶段 | 方案 | 闭合 | 胜率 | 均值 | 复利 | 回撤 | 硬亏率 |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for phase, metrics in _mapping(selected.get("phases")).items():
            chosen = _mapping(metrics)
            lines.append(_strict_row(str(phase), "selected", chosen))
        account = _mapping(selected.get("two_slot_account"))
        if account:
            lines.append(_strict_row("OOS+holdout", "两仓账户", account))
    lines.extend(
        [
            "",
            "## Evidence Boundary",
            "",
            "- JSON 包含全部 165 个组合及每个固定分批指标；Markdown 只显示每个窗口的描述性首位，避免把事后最高者误读为可交易规则。",
            "- 高收益日赢家和 D+1 收益只作结算后的覆盖统计，绝不作为入选字段。",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the isolated read-only study and write requested evidence files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = run_research(start=arguments.start, end=arguments.end)
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


def _variant_report(
    mother: pd.DataFrame,
    variant: GridVariant,
    strict_plan: Mapping[str, object],
) -> dict[str, object]:
    selected = mother.loc[variant_mask(mother, variant)].copy()
    return {
        **_variant_descriptor(variant),
        "full": _signal_summary(selected, mother),
        "descriptive_batches": {
            label: _signal_summary(
                _date_subset(selected, start, end),
                _date_subset(mother, start, end),
            )
            for label, start, end in DESCRIPTIVE_BATCHES
        },
        "strict": _strict_metrics(selected, mother, strict_plan),
    }


def _strict_metrics(
    selected: pd.DataFrame,
    mother: pd.DataFrame,
    strict_plan: Mapping[str, object],
) -> dict[str, object]:
    if strict_plan.get("status") != "ready":
        return {}
    training = _phase_summary(selected, mother, _mapping(strict_plan.get("training")))
    calibration = _phase_summary(
        selected,
        mother,
        _mapping(strict_plan.get("calibration")),
    )
    oos = [
        _phase_summary(selected, mother, _mapping(phase))
        for phase in _sequence(strict_plan.get("oos"))
    ]
    holdout = _phase_summary(selected, mother, _mapping(strict_plan.get("holdout")))
    return {
        "training": training,
        "calibration": calibration,
        "oos": oos,
        "holdout": holdout,
    }


def _phase_summary(
    selected: pd.DataFrame,
    mother: pd.DataFrame,
    phase: Mapping[str, object],
) -> dict[str, object]:
    start = _as_date(phase.get("start"))
    end = _as_date(phase.get("end"))
    mature_before = _as_date(phase.get("mature_before"))
    if start is None or end is None:
        return _signal_summary(selected.iloc[0:0], mother.iloc[0:0])
    selected_phase = _date_subset(selected, start, end)
    mother_phase = _date_subset(mother, start, end)
    if mature_before is not None:
        selected_phase = _mature_before(selected_phase, mature_before)
        mother_phase = _mature_before(mother_phase, mature_before)
    return _signal_summary(selected_phase, mother_phase)


def _strict_result(
    selected_name: str | None,
    reports: Mapping[str, Mapping[str, object]],
    baseline: Mapping[str, object],
    strict_plan: Mapping[str, object],
    mother: pd.DataFrame,
    trade_dates: Sequence[date],
    official_daily_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if strict_plan.get("status") != "ready":
        return {
            "status": "INSUFFICIENT_STRICT_VALIDATION",
            "reason": "candidate_history_shorter_than_frozen_strict_windows",
        }
    if selected_name is None:
        return {
            "status": "REJECT",
            "reason": "no_variant_meets_training_and_calibration_minimums",
        }
    selected_report = _mapping(reports.get(selected_name))
    selected_strict = _mapping(selected_report.get("strict"))
    baseline_strict = _mapping(baseline.get("strict"))
    phase_reports: dict[str, dict[str, object]] = {
        "training": _mapping(selected_strict.get("training")),
        "calibration": _mapping(selected_strict.get("calibration")),
        "holdout": _mapping(selected_strict.get("holdout")),
    }
    baseline_phases: dict[str, dict[str, object]] = {
        "training": _mapping(baseline_strict.get("training")),
        "calibration": _mapping(baseline_strict.get("calibration")),
        "holdout": _mapping(baseline_strict.get("holdout")),
    }
    selected_oos = _sequence(selected_strict.get("oos"))
    baseline_oos = _sequence(baseline_strict.get("oos"))
    for index, payload in enumerate(selected_oos, start=1):
        name = f"oos_{index}"
        phase_reports[name] = _mapping(payload)
        baseline_phases[name] = (
            _mapping(baseline_oos[index - 1])
            if index <= len(baseline_oos)
            else {}
        )
    passed_phases = all(
        _phase_passes(metrics, baseline_phases.get(name, {}))
        for name, metrics in phase_reports.items()
    )
    oos_phases = _sequence(strict_plan.get("oos"))
    oos_holdout_start = (
        _as_date(oos_phases[0].get("start")) if oos_phases else None
    )
    validation_selected = (
        _date_subset(mother, oos_holdout_start, date.max)
        if oos_holdout_start is not None
        else mother.iloc[0:0]
    )
    selected_variant = _variant_from_report(selected_report)
    validation_selected = validation_selected.loc[
        variant_mask(validation_selected, selected_variant)
    ]
    validation_baseline = _date_subset(mother, oos_holdout_start, date.max)
    validation_baseline = validation_baseline.loc[
        variant_mask(validation_baseline, BASELINE_VARIANT)
    ]
    bootstrap = date_block_bootstrap_delta(validation_baseline, validation_selected)
    accounts = _validation_two_slot_accounts(
        validation_baseline,
        validation_selected,
        trade_dates=trade_dates,
        official_daily_bars=official_daily_bars,
    )
    account_passed = _account_passes(
        _mapping(accounts.get("baseline")),
        _mapping(accounts.get("selected")),
    )
    bootstrap_passed = _number(bootstrap.get("mean_delta_lower_95")) is not None and (
        _number(bootstrap.get("mean_delta_lower_95")) > 0
    )
    status = "SHADOW_ONLY" if passed_phases and account_passed and bootstrap_passed else "REJECT"
    return {
        "status": status,
        "selected": {
            "name": selected_name,
            "phases": phase_reports,
            "baseline_phases": baseline_phases,
            "bootstrap": bootstrap,
            "two_slot_account": _mapping(accounts.get("selected")),
            "baseline_two_slot_account": _mapping(accounts.get("baseline")),
        },
        "acceptance": {
            "phase_gates_passed": passed_phases,
            "bootstrap_lower_95_positive": bootstrap_passed,
            "two_slot_account_passed": account_passed,
        },
    }


def _validation_two_slot_accounts(
    baseline: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    trade_dates: Sequence[date],
    official_daily_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not official_daily_bars:
        return {}
    return {
        "baseline": _simulate_two_slot(baseline, trade_dates, official_daily_bars),
        "selected": _simulate_two_slot(selected, trade_dates, official_daily_bars),
    }


def _simulate_two_slot(
    frame: pd.DataFrame,
    trade_dates: Sequence[date],
    bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    signals: list[dict[str, object]] = []
    for raw in frame.sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"],
        kind="stable",
    ).to_dict("records"):
        row = dict(raw)
        industry_ratio = _number(row.get("prior_industry_turnover_ratio_5d"))
        row["quality_priority_tier"] = (
            "A_industry_expanding"
            if industry_ratio is not None and industry_ratio >= 1.0
            else "B_recognition_only"
        )
        signals.append(row)
    account = cash_backtest.simulate_limit_up_account(
        signals,
        bars,
        trade_dates,
        "next_close",
        cash_backtest.CashBacktestConfig(initial_cash=100_000, max_positions=2),
    )
    return _mapping(account.get("execution_summary"))


def _phase_passes(
    metrics: Mapping[str, object],
    baseline: Mapping[str, object],
) -> bool:
    closed = _integer(metrics.get("closed_count"))
    win_rate = _number(metrics.get("win_rate_pct"))
    average = _number(metrics.get("average_return_pct"))
    hard_loss = _number(metrics.get("hard_loss_rate_pct"))
    drawdown = _number(metrics.get("maximum_drawdown_pct"))
    baseline_hard_loss = _number(baseline.get("hard_loss_rate_pct"))
    baseline_drawdown = _number(baseline.get("maximum_drawdown_pct"))
    return bool(
        closed >= MINIMUM_STRICT_CLOSED_COUNT
        and win_rate is not None
        and win_rate >= 60.0
        and average is not None
        and average > 0
        and hard_loss is not None
        and baseline_hard_loss is not None
        and hard_loss <= baseline_hard_loss
        and drawdown is not None
        and baseline_drawdown is not None
        and drawdown >= baseline_drawdown
    )


def _account_passes(
    baseline: Mapping[str, object],
    selected: Mapping[str, object],
) -> bool:
    baseline_return = _number(baseline.get("total_return_pct"))
    selected_return = _number(selected.get("total_return_pct"))
    baseline_drawdown = _number(baseline.get("max_drawdown_pct"))
    selected_drawdown = _number(selected.get("max_drawdown_pct"))
    baseline_hard_loss = _number(baseline.get("hard_loss_rate"))
    selected_hard_loss = _number(selected.get("hard_loss_rate"))
    return bool(
        baseline_return is not None
        and selected_return is not None
        and selected_return > baseline_return
        and baseline_drawdown is not None
        and selected_drawdown is not None
        and selected_drawdown >= baseline_drawdown
        and baseline_hard_loss is not None
        and selected_hard_loss is not None
        and selected_hard_loss <= baseline_hard_loss
    )


def _descriptive_leaders(
    reports: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    leaders: dict[str, dict[str, object]] = {}
    for sessions in sorted(WINDOW_LABELS):
        eligible = [
            report
            for report in reports
            if _integer(report.get("window_sessions")) == sessions
            and _integer(_mapping(report.get("full")).get("closed_count"))
            >= MINIMUM_STRICT_CLOSED_COUNT
        ]
        if not eligible:
            continue
        selected = max(eligible, key=_descriptive_sort_key)
        leaders[str(sessions)] = {
            "name": str(selected.get("name") or ""),
            "lower": _integer(selected.get("lower")),
            "upper": _integer(selected.get("upper")),
        }
    return leaders


def _descriptive_sort_key(report: Mapping[str, object]) -> tuple[float, float, float, float, int, str]:
    summary = _mapping(report.get("full"))
    return (
        _sort_number(summary.get("daily_equal_weight_compounded_pct"), float("-inf")),
        _sort_number(summary.get("average_return_pct"), float("-inf")),
        _sort_number(summary.get("win_rate_pct"), float("-inf")),
        -_sort_number(summary.get("hard_loss_rate_pct"), float("inf")),
        _integer(summary.get("closed_count")),
        str(report.get("name") or ""),
    )


def _selection_phase_ready(metrics: Mapping[str, object]) -> bool:
    return bool(
        _integer(metrics.get("closed_count")) >= MINIMUM_STRICT_CLOSED_COUNT
        and _sort_number(metrics.get("win_rate_pct"), float("-inf")) >= 60.0
        and _sort_number(metrics.get("average_return_pct"), float("-inf")) > 0
    )


def _calibration_sort_key(report: Mapping[str, object]) -> tuple[float, float, float, float, int, str]:
    calibration = _mapping(_mapping(report.get("strict")).get("calibration"))
    return (
        _sort_number(
            calibration.get("daily_equal_weight_compounded_pct"), float("-inf")
        ),
        _sort_number(calibration.get("average_return_pct"), float("-inf")),
        _sort_number(calibration.get("win_rate_pct"), float("-inf")),
        -_sort_number(calibration.get("hard_loss_rate_pct"), float("inf")),
        _integer(calibration.get("closed_count")),
        str(report.get("name") or ""),
    )


def _signal_summary(selected: pd.DataFrame, mother: pd.DataFrame) -> dict[str, object]:
    summary = performance_summary(selected, baseline_count=len(mother))
    returns = _numeric_series(selected, "return_pct")
    high_return = returns.ge(HIGH_RETURN_PCT)
    daily_top = _daily_top_high_return(mother)
    selected_ids = {
        identity
        for row in selected.to_dict("records")
        if (identity := _identity(row)) is not None
    }
    captured = sum(
        _identity(row) in selected_ids for row in daily_top.to_dict("records")
    )
    high_count = int(high_return.sum())
    closed_count = _integer(summary.get("closed_count"))
    return {
        **summary,
        "candidate_trade_days": int(selected["trade_date"].nunique()) if not selected.empty else 0,
        "high_return_count": high_count,
        "high_return_rate_pct": _rate(high_count, closed_count),
        "daily_top_high_return_count": int(len(daily_top)),
        "daily_top_high_return_captured_count": captured,
        "daily_top_high_return_capture_pct": _rate(captured, len(daily_top)),
    }


def _daily_top_high_return(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.iloc[0:0].copy()
    high = frame.loc[_numeric_series(frame, "return_pct").ge(HIGH_RETURN_PCT)].copy()
    if high.empty:
        return high
    return high.sort_values(
        ["trade_date", "return_pct", "vt_symbol"],
        ascending=[True, False, True],
        kind="stable",
    ).groupby("trade_date", sort=False).head(1)


def _date_subset(frame: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    if frame.empty or start is None or end is None:
        return frame.iloc[0:0].copy()
    dates = _date_series(frame, "trade_date")
    return frame.loc[dates.between(start, end)].copy()


def _mature_before(frame: pd.DataFrame, boundary: date) -> pd.DataFrame:
    result_dates = _date_series(frame, "result_date")
    return frame.loc[result_dates.lt(boundary)].copy()


def _returns_by_date(frame: pd.DataFrame) -> dict[date, tuple[float, ...]]:
    if frame.empty:
        return {}
    records: dict[date, list[float]] = {}
    for row in frame.to_dict("records"):
        signal_date = _as_date(row.get("trade_date"))
        return_pct = _number(row.get("return_pct"))
        if signal_date is None or return_pct is None:
            continue
        records.setdefault(signal_date, []).append(return_pct)
    return {key: tuple(values) for key, values in records.items()}


def _input_integrity(frame: pd.DataFrame) -> dict[str, object]:
    verified = _boolean_series(frame, "count_evidence_verified")
    total = len(frame)
    return {
        "status": "ready" if total == int(verified.sum()) else "count_reconciliation_failed",
        "closed_candidate_count": total,
        "verified_count": int(verified.sum()),
        "unverified_count": total - int(verified.sum()),
    }


def _research_decision(
    status: str,
    strict_plan: Mapping[str, object],
) -> dict[str, object]:
    if status == "INPUT_DRIFT_REJECTED":
        return {
            "formal_action": "KEEP_CURRENT_126_2_TO_6",
            "reason": "recomputed 126-session counts do not reconcile with frozen candidates",
        }
    if strict_plan.get("status") != "ready":
        return {
            "formal_action": "KEEP_CURRENT_126_2_TO_6",
            "reason": (
                "冻结严格验证可用的候选交易日只有 "
                f"{_integer(strict_plan.get('candidate_session_count'))}/"
                f"{_integer(strict_plan.get('required_session_count'))}"
            ),
        }
    if status == "SHADOW_ONLY":
        return {
            "formal_action": "SHADOW_ONLY",
            "reason": "historical gates passed; natural forward evidence remains required",
        }
    return {
        "formal_action": "KEEP_CURRENT_126_2_TO_6",
        "reason": "no calibration-selected variant passed every fixed validation gate",
    }


def _input_fingerprint(frame: pd.DataFrame) -> str:
    columns = [
        field
        for field in (
            "trade_date",
            "vt_symbol",
            "return_pct",
            "frozen_prior_limit_count_126",
            "prior_limit_count_42",
            "prior_limit_count_63",
            "prior_limit_count_126",
            "count_evidence_verified",
        )
        if field in frame
    ]
    payload = (
        frame.loc[:, columns]
        .sort_values([field for field in ("trade_date", "vt_symbol") if field in columns])
        .to_json(orient="records", date_format="iso", force_ascii=True)
        if columns
        else "[]"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _variant_descriptor(variant: GridVariant) -> dict[str, object]:
    return {
        "name": variant.name,
        "window_sessions": variant.window_sessions,
        "window_label": variant.window_label,
        "lower": variant.lower,
        "upper": variant.upper,
        "count_field": variant.count_field,
    }


def _variant_from_report(report: Mapping[str, object]) -> GridVariant:
    return GridVariant(
        _integer(report.get("window_sessions")),
        _integer(report.get("lower")),
        _integer(report.get("upper")),
    )


def _strict_plan_unavailable(
    session_count: int,
    first_signal: date | None,
    last_signal: date | None,
) -> dict[str, object]:
    required = (
        STRICT_TRAINING_SESSIONS
        + STRICT_CALIBRATION_SESSIONS
        + STRICT_TEST_SESSIONS
        + STRICT_HOLDOUT_SESSIONS
    )
    return {
        "status": "INSUFFICIENT_STRICT_VALIDATION",
        "candidate_session_count": session_count,
        "required_session_count": required,
        "candidate_start": first_signal.isoformat() if first_signal else None,
        "candidate_end": last_signal.isoformat() if last_signal else None,
    }


def _count_audit(
    matched_count: int,
    mismatched_count: int,
    missing_count: int,
    examples: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "status": "ready" if not mismatched_count and not missing_count else "failed",
        "matched_count": matched_count,
        "mismatched_count": mismatched_count,
        "missing_count": missing_count,
        "examples": [dict(item) for item in examples],
    }


def _count_fields() -> tuple[str, ...]:
    return tuple(f"prior_limit_count_{sessions}" for sessions in sorted(WINDOW_LABELS))


def _identity(row: Mapping[str, object]) -> tuple[date, str] | None:
    signal_date = _as_date(
        row.get("trade_date")
        or row.get("signal_date")
        or row.get("entry_date")
    )
    symbol = str(row.get("vt_symbol") or "").strip()
    return (signal_date, symbol) if signal_date is not None and symbol else None


def _date_series(frame: pd.DataFrame, field: str) -> pd.Series:
    values = pd.to_datetime(
        frame.get(field, pd.Series(index=frame.index, dtype=object)),
        errors="coerce",
    )
    return values.dt.date


def _numeric_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(
        frame.get(field, pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )


def _boolean_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series(False, index=frame.index, dtype=bool)).eq(True)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _optional_integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _sort_number(value: object, default: float) -> float:
    number = _number(value)
    return number if number is not None else default


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 4)


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number:.2f}%" if number is not None else "-"


def _signed_pct(value: object) -> str:
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _summary_table_row(label: str, summary: Mapping[str, object]) -> str:
    return "| " + " | ".join(
        [
            label,
            str(_integer(summary.get("closed_count"))),
            _pct(summary.get("win_rate_pct")),
            _signed_pct(summary.get("average_return_pct")),
            _signed_pct(summary.get("daily_equal_weight_compounded_pct")),
            _signed_pct(summary.get("maximum_drawdown_pct")),
            _pct(summary.get("hard_loss_rate_pct")),
            f"{_integer(summary.get('daily_top_high_return_captured_count'))}/"
            f"{_integer(summary.get('daily_top_high_return_count'))}",
        ]
    ) + " |"


def _strict_row(phase: str, label: str, summary: Mapping[str, object]) -> str:
    return "| " + " | ".join(
        [
            phase,
            label,
            str(_integer(_first_present(summary, "closed_count", "trade_count"))),
            _pct(_first_present(summary, "win_rate_pct", "win_rate")),
            _signed_pct(summary.get("average_return_pct")),
            _signed_pct(
                _first_present(
                    summary,
                    "daily_equal_weight_compounded_pct",
                    "total_return_pct",
                )
            ),
            _signed_pct(
                _first_present(summary, "maximum_drawdown_pct", "max_drawdown_pct")
            ),
            _pct(_first_present(summary, "hard_loss_rate_pct", "hard_loss_rate")),
        ]
    ) + " |"


def _first_present(mapping: Mapping[str, object], *fields: str) -> object:
    for field in fields:
        value = mapping.get(field)
        if value is not None:
            return value
    return None


if __name__ == "__main__":
    main()
