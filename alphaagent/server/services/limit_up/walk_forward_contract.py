"""Frozen point-in-time contract for limit-up walk-forward research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from math import isfinite
from typing import Mapping, Sequence

from alphaagent.server.services.limit_up.versions import (
    WALK_FORWARD_MODEL_VERSION as MODEL_VERSION,
)

ENTRY_MODES = ("auction", "sweep", "tail", "next_auction")
EXIT_MODES = ("next_open", "next_close")
BOARD_LANES = ("first_board", "one_to_two", "two_to_three", "high_board")
BOARD_LANE_ENTRY_MODES = {
    "first_board": "sweep",
    "one_to_two": "next_auction",
    "two_to_three": "next_auction",
    "high_board": "next_auction",
}
MARKET_PHASES = ("retreat", "mixed", "repair", "broad_rise", "unknown")
NUMERIC_FEATURE_NAMES = (
    "auction_gap_pct",
    "prior_change_pct",
    "prior_return_5d_pct",
    "prior_return_20d_pct",
    "prior_turnover_rate",
    "prior_amount_ratio_5d",
    "prior_amplitude_pct",
    "prior_industry_heat_score",
    "prior_industry_leadership_score",
    "prior_industry_change_pct",
    "prior_industry_return_5d_pct",
    "prior_industry_advancing_rate",
    "prior_industry_turnover_ratio_5d",
    "prior_market_advancing_rate",
    "prior_market_failed_rate",
    "prior_market_one_to_two_rate",
    "prior_market_two_to_three_rate",
)
LANE_NUMERIC_FEATURE_NAMES = (
    "signal_minute",
    "prior_limit_count_126",
    "prior_touch_count_126",
    "prior_seal_success_rate_126",
    "trade_days_since_prior_limit",
    "pullback_from_prior_limit_pct",
    "prior_position_120",
    "prior_industry_leader_rank",
    "prior_board_open_times",
    "prior_board_first_limit_minute",
    "prior_board_last_limit_minute",
    "prior_board_seal_to_turnover_ratio",
    "prior_board_turnover_rate",
    "path_touch_count",
    "path_break_count",
    "path_reseal_count",
    "intraday_support_floor_pct",
    "path_recent_15m_min_pct",
    "path_recent_15m_change_pct",
    "path_recent_15m_range_pct",
    "path_recent_15m_drawdown_pct",
    "path_recent_30m_min_pct",
    "path_recent_30m_change_pct",
    "path_approach_3point_pct",
    "intraday_support_score",
    "first_board_entry_quality_score",
    "financial_report_available",
    "financial_risk_count",
    "financial_blocked",
    "financial_revenue_yoy",
    "financial_net_profit_yoy",
    "financial_gross_margin",
    "financial_roe",
    "financial_debt_asset_ratio",
    "financial_cash_flow_quality",
)
FEATURE_NAMES = (
    *NUMERIC_FEATURE_NAMES,
    *LANE_NUMERIC_FEATURE_NAMES,
    "target_board",
    "prior_streak",
    *(f"market_phase_{phase}" for phase in MARKET_PHASES),
)


@dataclass(frozen=True)
class WalkForwardConfig:
    training_days: int = 252
    calibration_days: int = 63
    test_days: int = 63
    holdout_days: int = 120
    max_daily_plans: int = 2
    min_training_samples: int = 300
    bootstrap_samples: int = 200
    estimator_count: int = 80
    random_seed: int = 20260711
    minimum_fill_probability: float = 0.50
    minimum_seal_probability: float = 0.55
    minimum_profit_probability: float = 0.55
    minimum_expected_return_pct: float = 0.0
    minimum_confidence_lower_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.training_days <= 0:
            raise ValueError("training_days must be positive")
        if not 0 < self.calibration_days < self.training_days:
            raise ValueError("calibration_days must be between zero and training_days")
        if self.test_days <= 0:
            raise ValueError("test_days must be positive")
        if self.holdout_days < 0:
            raise ValueError("holdout_days cannot be negative")
        if self.max_daily_plans <= 0:
            raise ValueError("max_daily_plans must be positive")
        if self.min_training_samples <= 0:
            raise ValueError("min_training_samples must be positive")
        if self.bootstrap_samples <= 0:
            raise ValueError("bootstrap_samples must be positive")
        if self.estimator_count <= 0:
            raise ValueError("estimator_count must be positive")


DEFAULT_CONFIG = WalkForwardConfig()


@dataclass(frozen=True)
class ModelSample:
    signal_date: date
    result_date: date
    vt_symbol: str
    name: str
    industry_name: str
    rank: int
    target_board: int
    features: tuple[float, ...]
    fill_proxy: bool | None
    sealed: bool
    return_pct: float
    profitable: bool
    execution_confidence: str
    candidate: Mapping[str, object]


@dataclass(frozen=True)
class WalkForwardWindow:
    phase: str
    sequence: int
    train_start: date
    calibration_start: date
    test_start: date
    test_end: date
    training_samples: tuple[ModelSample, ...]
    calibration_samples: tuple[ModelSample, ...]
    test_samples: tuple[ModelSample, ...]


def feature_vector(candidate: Mapping[str, object]) -> dict[str, float]:
    known = candidate.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    vector = {
        name: _finite_number(
            known.get(name, candidate.get(name)),
            default=float("nan"),
        )
        for name in NUMERIC_FEATURE_NAMES
    }
    prior_board = candidate.get("prior_board")
    prior_board = prior_board if isinstance(prior_board, Mapping) else {}
    path = candidate.get("path_prefix")
    path = path if isinstance(path, Mapping) else {}
    financial = candidate.get("financial_risk")
    financial = financial if isinstance(financial, Mapping) else {}
    financial_snapshot = candidate.get("financial_snapshot")
    financial_snapshot = (
        financial_snapshot if isinstance(financial_snapshot, Mapping) else {}
    )
    financial_reasons = financial.get("reasons")
    financial_reasons = (
        financial_reasons
        if isinstance(financial_reasons, Sequence)
        and not isinstance(financial_reasons, (str, bytes))
        else []
    )
    vector.update(
        {
            "signal_minute": _minute_value(candidate.get("signal_time")),
            "prior_limit_count_126": _finite_number(
                candidate.get("prior_limit_count_126"), default=float("nan")
            ),
            "prior_touch_count_126": _finite_number(
                candidate.get("prior_touch_count_126"), default=float("nan")
            ),
            "prior_seal_success_rate_126": _finite_number(
                candidate.get("prior_seal_success_rate_126"), default=float("nan")
            ),
            "trade_days_since_prior_limit": _finite_number(
                candidate.get("trade_days_since_prior_limit"), default=float("nan")
            ),
            "pullback_from_prior_limit_pct": _finite_number(
                candidate.get("pullback_from_prior_limit_pct"), default=float("nan")
            ),
            "prior_position_120": _finite_number(
                candidate.get("prior_position_120"), default=float("nan")
            ),
            "prior_industry_leader_rank": _finite_number(
                candidate.get("prior_industry_leader_rank"), default=float("nan")
            ),
            "prior_board_open_times": _finite_number(
                prior_board.get("open_times"), default=float("nan")
            ),
            "prior_board_first_limit_minute": _minute_value(
                prior_board.get("first_limit_time")
            ),
            "prior_board_last_limit_minute": _minute_value(
                prior_board.get("last_limit_time")
            ),
            "prior_board_seal_to_turnover_ratio": _finite_number(
                prior_board.get("seal_to_turnover_ratio"), default=float("nan")
            ),
            "prior_board_turnover_rate": _finite_number(
                prior_board.get("turnover_rate"), default=float("nan")
            ),
            "path_touch_count": _finite_number(
                path.get("touch_count"), default=float("nan")
            ),
            "path_break_count": _finite_number(
                path.get("break_count"), default=float("nan")
            ),
            "path_reseal_count": _finite_number(
                path.get("reseal_count"), default=float("nan")
            ),
            "intraday_support_floor_pct": _finite_number(
                path.get("minimum_pct", candidate.get("session_low_change_pct")),
                default=float("nan"),
            ),
            "path_recent_15m_min_pct": _finite_number(
                path.get("recent_15m_min_pct"), default=float("nan")
            ),
            "path_recent_15m_change_pct": _finite_number(
                path.get("recent_15m_change_pct"), default=float("nan")
            ),
            "path_recent_15m_range_pct": _finite_number(
                path.get("recent_15m_range_pct"), default=float("nan")
            ),
            "path_recent_15m_drawdown_pct": _finite_number(
                path.get("recent_15m_drawdown_pct"), default=float("nan")
            ),
            "path_recent_30m_min_pct": _finite_number(
                path.get("recent_30m_min_pct"), default=float("nan")
            ),
            "path_recent_30m_change_pct": _finite_number(
                path.get("recent_30m_change_pct"), default=float("nan")
            ),
            "path_approach_3point_pct": _finite_number(
                path.get("approach_3point_pct"), default=float("nan")
            ),
            "intraday_support_score": _finite_number(
                candidate.get("support_score"), default=float("nan")
            ),
            "first_board_entry_quality_score": _finite_number(
                candidate.get("entry_quality_score"), default=float("nan")
            ),
            "financial_report_available": float(financial.get("level") != "unknown"),
            "financial_risk_count": float(len(financial_reasons)),
            "financial_blocked": float(financial.get("blocked") is True),
            "financial_revenue_yoy": _finite_number(
                financial_snapshot.get("revenue_yoy"), default=float("nan")
            ),
            "financial_net_profit_yoy": _finite_number(
                financial_snapshot.get("net_profit_yoy"), default=float("nan")
            ),
            "financial_gross_margin": _finite_number(
                financial_snapshot.get("gross_margin"), default=float("nan")
            ),
            "financial_roe": _finite_number(
                financial_snapshot.get("roe"), default=float("nan")
            ),
            "financial_debt_asset_ratio": _finite_number(
                financial_snapshot.get("debt_asset_ratio"), default=float("nan")
            ),
            "financial_cash_flow_quality": _finite_number(
                financial_snapshot.get("cash_flow_quality"), default=float("nan")
            ),
        }
    )
    vector["target_board"] = _finite_number(candidate.get("target_board"), default=1.0)
    vector["prior_streak"] = _finite_number(candidate.get("prior_streak"), default=0.0)
    phase = str(known.get("prior_market_phase") or "unknown")
    if phase not in MARKET_PHASES:
        phase = "unknown"
    vector.update(
        {
            f"market_phase_{candidate_phase}": float(candidate_phase == phase)
            for candidate_phase in MARKET_PHASES
        }
    )
    return {name: vector[name] for name in FEATURE_NAMES}


def build_model_samples(
    days: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
    exit_mode: str,
    board_lane: str | None = None,
) -> list[ModelSample]:
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"unsupported entry mode: {entry_mode}")
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    if board_lane is not None and board_lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {board_lane}")
    return_field = "next_open_return_pct" if exit_mode == "next_open" else "next_close_return_pct"
    samples: list[ModelSample] = []
    for day in days:
        day_date = _date_value(day.get("trade_date"))
        candidates = _model_candidate_rows(day, entry_mode, board_lane)
        for raw_candidate in candidates:
            if day_date is None or not isinstance(raw_candidate, Mapping):
                continue
            candidate = dict(raw_candidate)
            signal_date = _date_value(candidate.get("signal_date")) or day_date
            result_date = _date_value(candidate.get("result_date"))
            outcome = candidate.get("outcome")
            outcome = outcome if isinstance(outcome, Mapping) else {}
            return_pct = _number(outcome.get(return_field))
            if result_date is None or result_date <= signal_date or return_pct is None:
                continue
            vector = feature_vector(candidate)
            samples.append(
                ModelSample(
                    signal_date=signal_date,
                    result_date=result_date,
                    vt_symbol=str(candidate.get("vt_symbol") or ""),
                    name=str(candidate.get("name") or ""),
                    industry_name=str(candidate.get("industry_name") or "行业待确认"),
                    rank=int(
                        _finite_number(
                            candidate.get("pool_rank", candidate.get("rank")),
                            default=0.0,
                        )
                    ),
                    target_board=int(_finite_number(candidate.get("target_board"), default=1.0)),
                    features=tuple(vector[name] for name in FEATURE_NAMES),
                    fill_proxy=_fill_proxy(entry_mode, outcome),
                    sealed=bool(outcome.get("sealed")),
                    return_pct=return_pct,
                    profitable=return_pct > 0,
                    execution_confidence=str(candidate.get("execution_confidence") or "unknown"),
                    candidate=candidate,
                )
            )
    return sorted(samples, key=lambda sample: (sample.signal_date, sample.rank, sample.vt_symbol))


def _model_candidate_rows(
    day: Mapping[str, object],
    entry_mode: str,
    board_lane: str | None,
) -> list[Mapping[str, object]]:
    if board_lane is None:
        lanes = day.get("lanes")
        lanes = lanes if isinstance(lanes, Mapping) else {}
        rows = lanes.get(entry_mode)
        return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    pool = day.get("board_candidate_pool")
    pool = pool if isinstance(pool, Mapping) else {}
    rows = pool.get(board_lane)
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, Mapping)
        and (
            row.get("decision") == "eligible"
            or (
                board_lane == "first_board"
                and _first_board_model_pool_candidate(row)
            )
        )
    ]


def _first_board_model_pool_candidate(candidate: Mapping[str, object]) -> bool:
    blockers = candidate.get("blockers")
    if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
        return False
    selection_only = {
        "first_board_local_setup_unconfirmed",
        "first_board_quality_below_threshold",
        "first_board_touch_gene_weak",
        "financial_report_unavailable",
        "first_board_profit_growth_weak",
        "first_board_repair_setup_missing",
    }
    normalized = {str(blocker) for blocker in blockers}
    return bool(normalized) and normalized <= selection_only


def build_walk_forward_windows(
    samples: Sequence[ModelSample],
    *,
    config: WalkForwardConfig = DEFAULT_CONFIG,
    trading_dates: Sequence[date] | None = None,
) -> list[WalkForwardWindow]:
    dates = sorted(
        set(trading_dates)
        if trading_dates is not None
        else {sample.signal_date for sample in samples}
    )
    calendar = set(dates)
    if any(sample.signal_date not in calendar for sample in samples):
        raise ValueError("sample signal date is missing from trading calendar")
    if len(dates) <= config.training_days:
        return []
    holdout_start_index = max(len(dates) - config.holdout_days, config.training_days)
    windows: list[WalkForwardWindow] = []
    sequence = 1
    for test_start_index in range(config.training_days, holdout_start_index, config.test_days):
        test_end_index = min(test_start_index + config.test_days, holdout_start_index) - 1
        windows.append(
            _window(
                samples,
                dates,
                phase="expanding_oos",
                sequence=sequence,
                test_start_index=test_start_index,
                test_end_index=test_end_index,
                config=config,
            )
        )
        sequence += 1
    if config.holdout_days > 0 and holdout_start_index < len(dates):
        windows.append(
            _window(
                samples,
                dates,
                phase="locked_holdout",
                sequence=sequence,
                test_start_index=holdout_start_index,
                test_end_index=len(dates) - 1,
                config=config,
            )
        )
    return windows


def _window(
    samples: Sequence[ModelSample],
    dates: Sequence[date],
    *,
    phase: str,
    sequence: int,
    test_start_index: int,
    test_end_index: int,
    config: WalkForwardConfig,
) -> WalkForwardWindow:
    train_start_index = test_start_index - config.training_days
    calibration_start_index = test_start_index - config.calibration_days
    train_start = dates[train_start_index]
    calibration_start = dates[calibration_start_index]
    test_start = dates[test_start_index]
    test_end = dates[test_end_index]
    matured = [sample for sample in samples if sample.result_date < test_start]
    training_samples = tuple(
        sample
        for sample in matured
        if train_start <= sample.signal_date < calibration_start
    )
    calibration_samples = tuple(
        sample
        for sample in matured
        if calibration_start <= sample.signal_date < test_start
    )
    test_samples = tuple(
        sample
        for sample in samples
        if test_start <= sample.signal_date <= test_end
    )
    return WalkForwardWindow(
        phase=phase,
        sequence=sequence,
        train_start=train_start,
        calibration_start=calibration_start,
        test_start=test_start,
        test_end=test_end,
        training_samples=training_samples,
        calibration_samples=calibration_samples,
        test_samples=test_samples,
    )


def _fill_proxy(entry_mode: str, outcome: Mapping[str, object]) -> bool | None:
    if entry_mode in {"auction", "next_auction"}:
        return True
    if entry_mode == "sweep":
        return bool(outcome.get("touched"))
    return None


def _date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _finite_number(value: object, *, default: float) -> float:
    number = _number(value)
    return number if number is not None else default


def _minute_value(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return float("nan")
    try:
        parsed = time.fromisoformat(text[:8])
    except ValueError:
        return float("nan")
    return float(parsed.hour * 60 + parsed.minute + parsed.second / 60)
