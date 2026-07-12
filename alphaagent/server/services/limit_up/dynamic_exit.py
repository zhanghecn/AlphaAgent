"""Point-in-time D+1 exit decisions for selected limit-up signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import log1p
from typing import Mapping, Sequence

EXIT_POLICY_VERSION = "limit-up-dynamic-exit-v1"
EXIT_MODE_AUCTION = "auction_exit"
EXIT_MODE_TAIL = "tail_exit"
DEVELOPMENT_PHASES = frozenset({"warmup", "expanding_oos"})
LOCKED_HOLDOUT_PHASE = "locked_holdout"
MIN_HIGH_BOARD_SAMPLES = 12
MIN_SWITCHED_SAMPLES = 5


@dataclass(frozen=True)
class _Policy:
    auction_threshold: float | None
    sample_count: int
    training_cutoff: str | None
    baseline_log_growth: float | None = None
    policy_log_growth: float | None = None
    baseline_win_rate: float | None = None
    policy_win_rate: float | None = None


def attach_dynamic_exit_decisions(
    signals: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach decisions without allowing same-day or holdout outcomes into training."""

    result = [dict(signal) for signal in signals]
    indexed = sorted(
        enumerate(result),
        key=lambda item: (
            _date(item[1].get("result_date")) or date.max,
            str(item[1].get("vt_symbol") or ""),
        ),
    )
    development = [
        signal
        for _, signal in indexed
        if str(signal.get("validation_phase") or "") in DEVELOPMENT_PHASES
        and _closed_outcome(signal)
    ]
    frozen_policy = _fit_policy(development)

    for _, signal in indexed:
        decision_date = _date(signal.get("result_date"))
        phase = str(signal.get("validation_phase") or "")
        if phase == LOCKED_HOLDOUT_PHASE:
            policy = frozen_policy
        else:
            training = [
                sample
                for sample in development
                if decision_date is not None
                and (_date(sample.get("result_date")) or date.max) < decision_date
            ]
            policy = _fit_policy(training)
        signal["dynamic_exit"] = _decision(signal, policy)
    return result


def attach_replay_exit_decisions(
    replays: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach decisions to selected replay candidates while preserving replay order."""

    result = [dict(replay) for replay in replays]
    references: list[dict[str, object]] = []
    for replay in result:
        portfolio = replay.get("lane_portfolio")
        if not isinstance(portfolio, Mapping):
            continue
        selected = portfolio.get("selected")
        if not isinstance(selected, list):
            continue
        for candidate in selected:
            if isinstance(candidate, dict):
                references.append(candidate)

    decided = attach_dynamic_exit_decisions(references)
    for target, source in zip(references, decided, strict=True):
        target["dynamic_exit"] = source["dynamic_exit"]
    return result


def _fit_policy(training: Sequence[Mapping[str, object]]) -> _Policy:
    high_board = [
        row
        for row in training
        if str(row.get("lane") or "") == "high_board" and _closed_outcome(row)
    ]
    cutoff = max(
        (str(row.get("result_date") or "")[:10] for row in high_board),
        default=None,
    )
    if len(high_board) < MIN_HIGH_BOARD_SAMPLES:
        return _Policy(None, len(high_board), cutoff)

    baseline_returns = [_return_value(row, "next_close_return_pct") for row in high_board]
    baseline_log = _average_log_growth(baseline_returns)
    baseline_win = _win_rate(baseline_returns)
    best: tuple[float, float, float] | None = None
    for threshold in sorted({_return_value(row, "next_open_return_pct") for row in high_board}):
        switched = [
            row
            for row in high_board
            if _return_value(row, "next_open_return_pct") >= threshold
        ]
        if len(switched) < MIN_SWITCHED_SAMPLES:
            continue
        policy_returns = [
            _return_value(
                row,
                "next_open_return_pct"
                if _return_value(row, "next_open_return_pct") >= threshold
                else "next_close_return_pct",
            )
            for row in high_board
        ]
        policy_log = _average_log_growth(policy_returns)
        policy_win = _win_rate(policy_returns)
        if policy_log <= baseline_log or policy_win < baseline_win:
            continue
        score = (policy_log, policy_win, threshold)
        if best is None or score > best:
            best = score

    if best is None:
        return _Policy(
            None,
            len(high_board),
            cutoff,
            baseline_log_growth=baseline_log,
            policy_log_growth=baseline_log,
            baseline_win_rate=baseline_win,
            policy_win_rate=baseline_win,
        )
    policy_log, policy_win, threshold = best
    return _Policy(
        threshold,
        len(high_board),
        cutoff,
        baseline_log_growth=baseline_log,
        policy_log_growth=policy_log,
        baseline_win_rate=baseline_win,
        policy_win_rate=policy_win,
    )


def _decision(signal: Mapping[str, object], policy: _Policy) -> dict[str, object]:
    auction_return = _optional_return(signal, "next_open_return_pct")
    lane = str(signal.get("lane") or "")
    use_auction = bool(
        lane == "high_board"
        and policy.auction_threshold is not None
        and auction_return is not None
        and auction_return >= policy.auction_threshold
    )
    if use_auction:
        mode = EXIT_MODE_AUCTION
        reason_code = "validated_high_board_auction_take_profit"
        reason = "高板竞价强度进入开发期验证过的兑现区间，D+1竞价卖出"
    else:
        mode = EXIT_MODE_TAIL
        reason_code = (
            "tail_has_no_validated_auction_edge"
            if lane != "high_board" or policy.auction_threshold is not None
            else "tail_insufficient_auction_history"
        )
        reason = "竞价兑现尚无同时改善胜率与复利的样本外证据，持有至D+1尾盘"
    return {
        "policy_version": EXIT_POLICY_VERSION,
        "mode": mode,
        "reason_code": reason_code,
        "reason": reason,
        "decision_time": "09:25:00",
        "training_cutoff": policy.training_cutoff,
        "sample_count": policy.sample_count,
        "auction_proxy_return_pct": auction_return,
        "auction_threshold": policy.auction_threshold,
        "baseline_log_growth": _rounded(policy.baseline_log_growth),
        "policy_log_growth": _rounded(policy.policy_log_growth),
        "baseline_win_rate": _rounded(policy.baseline_win_rate),
        "policy_win_rate": _rounded(policy.policy_win_rate),
        "confidence": (
            "daily_open_proxy_validated"
            if policy.auction_threshold is not None
            else "insufficient_history"
        ),
    }


def _closed_outcome(signal: Mapping[str, object]) -> bool:
    return (
        _optional_return(signal, "next_open_return_pct") is not None
        and _optional_return(signal, "next_close_return_pct") is not None
        and _date(signal.get("result_date")) is not None
    )


def _optional_return(signal: Mapping[str, object], field: str) -> float | None:
    outcome = signal.get("outcome")
    if not isinstance(outcome, Mapping):
        return None
    value = outcome.get(field)
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _return_value(signal: Mapping[str, object], field: str) -> float:
    value = _optional_return(signal, field)
    if value is None:
        raise ValueError(f"missing dynamic-exit return: {field}")
    return value


def _average_log_growth(returns: Sequence[float]) -> float:
    return sum(log1p(max(value, -99.0) / 100) for value in returns) / len(returns)


def _win_rate(returns: Sequence[float]) -> float:
    return sum(value > 0 for value in returns) / len(returns)


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None
