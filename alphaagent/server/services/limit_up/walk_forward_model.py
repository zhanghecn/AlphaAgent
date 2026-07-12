"""Orchestrate strict point-in-time walk-forward limit-up research."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Mapping, Sequence

from lightgbm import __version__ as lightgbm_version
from sklearn import __version__ as sklearn_version

from alphaagent.server.services.limit_up.walk_forward_contract import (
    BOARD_LANES,
    BOARD_LANE_ENTRY_MODES,
    DEFAULT_CONFIG,
    ENTRY_MODES,
    EXIT_MODES,
    FEATURE_NAMES,
    MODEL_VERSION,
    ModelSample,
    WalkForwardConfig,
    WalkForwardWindow,
    build_model_samples,
    build_walk_forward_windows,
    feature_vector,
)
from alphaagent.server.services.limit_up.walk_forward_metrics import (
    acceptance_gates,
    performance_summary,
    probability_calibration_summary,
    rejection_summary,
)
from alphaagent.server.services.limit_up.walk_forward_training import (
    ModelBundle,
    fit_model_bundle,
    score_window,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION

__all__ = [
    "DEFAULT_CONFIG",
    "ENTRY_MODES",
    "EXIT_MODES",
    "FEATURE_NAMES",
    "MODEL_VERSION",
    "ModelSample",
    "WalkForwardConfig",
    "WalkForwardWindow",
    "build_model_samples",
    "build_walk_forward_model_report",
    "build_walk_forward_windows",
    "feature_vector",
]


def build_walk_forward_model_report(
    days: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
    exit_mode: str,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
    config: WalkForwardConfig = DEFAULT_CONFIG,
    board_lane: str | None = None,
) -> dict[str, object]:
    if evaluation_start and evaluation_end and evaluation_start > evaluation_end:
        raise ValueError("evaluation_start cannot be later than evaluation_end")
    if board_lane is not None and board_lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {board_lane}")
    model_entry_mode = (
        BOARD_LANE_ENTRY_MODES[board_lane] if board_lane is not None else entry_mode
    )
    daily_plan_limit = 1 if board_lane is not None else config.max_daily_plans
    samples = build_model_samples(
        days,
        entry_mode=model_entry_mode,
        exit_mode=exit_mode,
        board_lane=board_lane,
    )
    trading_dates = _history_trade_dates(days)
    windows = build_walk_forward_windows(
        samples,
        config=config,
        trading_dates=trading_dates,
    )
    coverage = dict(days[-1].get("coverage") or {}) if days else {}
    window_rows: list[dict[str, object]] = []
    selected_candidates: list[dict[str, object]] = []
    ranked_candidates: list[dict[str, object]] = []
    all_scored: list[dict[str, object]] = []
    for window in windows:
        bundle = fit_model_bundle(window, entry_mode=model_entry_mode, config=config)
        scored = score_window(
            window,
            bundle,
            entry_mode=model_entry_mode,
            config=config,
        )
        scored = [
            row
            for row in scored
            if _in_evaluation_range(row, evaluation_start, evaluation_end)
        ]
        if not scored:
            window_rows.append(
                _window_report(
                    window,
                    bundle,
                    [],
                    [],
                    [],
                    entry_mode=model_entry_mode,
                )
            )
            continue
        selected = _select_daily(scored, daily_plan_limit, eligible_only=True)
        ranked = _select_daily(scored, daily_plan_limit, eligible_only=False)
        all_scored.extend(scored)
        selected_candidates.extend(selected)
        ranked_candidates.extend(ranked)
        window_rows.append(
            _window_report(
                window,
                bundle,
                scored,
                selected,
                ranked,
                entry_mode=model_entry_mode,
            )
        )

    phase_summaries = _phase_summaries(selected_candidates, model_entry_mode)
    ranked_phase_summaries = _phase_summaries(ranked_candidates, model_entry_mode)
    stress = {
        "extra_round_trip_cost_pct": 0.31,
        "expanding_oos": performance_summary(
            _phase_rows(selected_candidates, "expanding_oos"),
            entry_mode=model_entry_mode,
            extra_cost_pct=0.31,
        ),
        "locked_holdout": performance_summary(
            _phase_rows(selected_candidates, "locked_holdout"),
            entry_mode=model_entry_mode,
            extra_cost_pct=0.31,
        ),
    }
    calibration_phases = {
        phase: probability_calibration_summary(
            _phase_rows(all_scored, phase),
            entry_mode=model_entry_mode,
        )
        for phase in ("expanding_oos", "locked_holdout")
    }
    calibration = calibration_phases["locked_holdout"]
    gates = acceptance_gates(phase_summaries, stress, calibration, coverage)
    fitted_windows = sum(row["model_status"] == "ready" for row in window_rows)
    evaluation_samples = [
        sample
        for sample in samples
        if (evaluation_start is None or sample.signal_date >= evaluation_start)
        and (evaluation_end is None or sample.signal_date <= evaluation_end)
    ]
    return {
        "status": "ready" if fitted_windows else "insufficient_training",
        "mode": "walk_forward_net_expectation_research",
        "model_version": MODEL_VERSION,
        "history_strategy_version": str(
            days[-1].get("strategy_version") or HISTORY_STRATEGY_VERSION
        )
        if days
        else HISTORY_STRATEGY_VERSION,
        "entry_mode": model_entry_mode,
        "board_lane": board_lane,
        "exit_mode": exit_mode,
        "upgrade_status": "eligible"
        if gates and all(bool(row["passed"]) for row in gates)
        else "research_only",
        "candidate_scope": (
            "complete_board_lane_candidate_pool"
            if board_lane is not None
            else "persisted_point_in_time_top5"
        ),
        "execution_scope": _execution_scope(model_entry_mode),
        "model_contract": _model_contract(
            config,
            max_daily_plans=daily_plan_limit,
        ),
        "evaluation_range": {
            "start": evaluation_start.isoformat() if evaluation_start else None,
            "end": evaluation_end.isoformat() if evaluation_end else None,
        },
        "coverage": {
            **coverage,
            "selected_trade_days": len({sample.signal_date for sample in evaluation_samples}),
            "closed_candidate_count": len(evaluation_samples),
            "walk_forward_windows": len(window_rows),
            "fitted_windows": fitted_windows,
        },
        "phase_summaries": phase_summaries,
        "ranked_phase_summaries": ranked_phase_summaries,
        "stress_test": stress,
        "calibration_scope": "locked_holdout_test_predictions",
        "calibration_phases": calibration_phases,
        "calibration": calibration,
        "acceptance_gates": gates,
        "windows": window_rows,
        "selected_candidates": selected_candidates,
        "ranked_candidates": ranked_candidates,
        "rejection_summary": rejection_summary(all_scored),
        "limitations": [
            (
                "模型只在该板位每日完整硬门候选池内做0-1只研究选择。"
                if board_lane is not None
                else "模型只在持久化历史Top5内做0-2只研究选择，不重写原始候选账本。"
            ),
            "最后120日使用留出开始前冻结的模型；留出标签不参与拟合、校准或阈值。",
            "扫板成交仅为日线触板代理，尾盘成交不可验证；没有Tick/L2时不能升级为模拟执行。",
            "当前行业成员来自现有快照，存在幸存者偏差，因此simulation_eligible固定为false。",
        ],
    }


def _phase_summaries(
    rows: Sequence[Mapping[str, object]],
    entry_mode: str,
) -> dict[str, object]:
    return {
        phase: performance_summary(
            _phase_rows(rows, phase),
            entry_mode=entry_mode,
        )
        for phase in ("expanding_oos", "locked_holdout")
    }


def _phase_rows(
    rows: Sequence[Mapping[str, object]],
    phase: str,
) -> list[Mapping[str, object]]:
    return [row for row in rows if row.get("validation_phase") == phase]


def _in_evaluation_range(
    row: Mapping[str, object],
    start: date | None,
    end: date | None,
) -> bool:
    signal_date = date.fromisoformat(str(row.get("signal_date"))[:10])
    return (start is None or signal_date >= start) and (end is None or signal_date <= end)


def _history_trade_dates(days: Sequence[Mapping[str, object]]) -> list[date]:
    result: list[date] = []
    for day in days:
        value = day.get("trade_date")
        try:
            result.append(date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue
    return sorted(set(result))


def _select_daily(
    rows: Sequence[Mapping[str, object]],
    limit: int,
    *,
    eligible_only: bool,
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if not eligible_only or bool(row.get("model_eligible")):
            grouped[str(row.get("signal_date") or "")].append(row)
    selected: list[dict[str, object]] = []
    for signal_date in sorted(grouped):
        ordered = sorted(grouped[signal_date], key=_ranking_key, reverse=True)
        selected.extend(
            {**dict(row), **({"research_rank": rank} if not eligible_only else {})}
            for rank, row in enumerate(ordered[:limit], start=1)
        )
    return selected


def _ranking_key(row: Mapping[str, object]) -> tuple[float, float, int, str]:
    return (
        float(row.get("model_ev_pct") or -1e9),
        float(row.get("seal_probability") or 0.0),
        -int(row.get("rank") or 999),
        str(row.get("vt_symbol") or ""),
    )


def _window_report(
    window: WalkForwardWindow,
    bundle: ModelBundle,
    scored: Sequence[Mapping[str, object]],
    selected: Sequence[Mapping[str, object]],
    ranked: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
) -> dict[str, object]:
    rejected = [row for row in scored if not bool(row.get("model_eligible"))]
    rejected.sort(key=_ranking_key, reverse=True)
    return {
        "sequence": window.sequence,
        "validation_phase": window.phase,
        "train_start": window.train_start.isoformat(),
        "calibration_start": window.calibration_start.isoformat(),
        "test_start": window.test_start.isoformat(),
        "test_end": window.test_end.isoformat(),
        "training_samples": len(window.training_samples),
        "calibration_samples": len(window.calibration_samples),
        "test_samples": len(window.test_samples),
        "model_status": bundle.status,
        "reason": bundle.reason,
        "fit_calibration": bundle.calibration,
        "calibration": probability_calibration_summary(scored, entry_mode=entry_mode),
        "top5_baseline": performance_summary(scored, entry_mode=entry_mode),
        "model_plan": performance_summary(selected, entry_mode=entry_mode),
        "ranked_top2": performance_summary(ranked, entry_mode=entry_mode),
        "selected_count": len(selected),
        "selected_examples": [dict(row) for row in selected[:5]],
        "rejected_examples": [dict(row) for row in rejected[:5]],
    }


def _model_contract(
    config: WalkForwardConfig,
    *,
    max_daily_plans: int | None = None,
) -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "lightgbm_version": lightgbm_version,
        "sklearn_version": sklearn_version,
        "feature_names": list(FEATURE_NAMES),
        "training_days": config.training_days,
        "calibration_days": config.calibration_days,
        "test_days": config.test_days,
        "holdout_days": config.holdout_days,
        "max_daily_plans": max_daily_plans or config.max_daily_plans,
        "min_training_samples": config.min_training_samples,
        "estimator_count": config.estimator_count,
        "random_seed": config.random_seed,
        "minimum_fill_probability": config.minimum_fill_probability,
        "minimum_seal_probability": config.minimum_seal_probability,
        "minimum_profit_probability": config.minimum_profit_probability,
        "minimum_expected_return_pct": config.minimum_expected_return_pct,
        "minimum_confidence_lower_pct": config.minimum_confidence_lower_pct,
        "selection_basis": "training_and_chronological_calibration_only",
    }


def _execution_scope(entry_mode: str) -> str:
    return {
        "auction": "daily_open_proxy",
        "next_auction": "daily_open_proxy",
        "sweep": "daily_touch_proxy_without_l2",
        "tail": "tail_fill_unverifiable",
    }[entry_mode]
