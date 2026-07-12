"""Point-in-time factor diagnostics for persisted limit-up Top5 candidates."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Mapping, Sequence

from alphaagent.server.services.limit_up.domain import main_board_limit_price

AUDIT_PHASES = ("expanding_oos", "locked_holdout")
ENTRY_MODES = ("auction", "sweep", "tail", "next_auction")
EXIT_MODES = ("next_open", "next_close")


@dataclass(frozen=True)
class FactorSpec:
    code: str
    label: str
    value_format: str


FACTOR_SPECS = (
    FactorSpec("prior_industry_heat_score", "行业热度代理", "score"),
    FactorSpec("prior_industry_leadership_score", "行业前排强度", "score"),
    FactorSpec("prior_industry_change_pct", "D-1行业涨幅", "percent"),
    FactorSpec("prior_industry_return_5d_pct", "行业5日收益", "percent"),
    FactorSpec("prior_industry_advancing_rate", "行业上涨占比", "ratio"),
    FactorSpec("prior_industry_turnover_ratio_5d", "行业量能/5日", "multiple"),
    FactorSpec("prior_market_advancing_rate", "D-1市场涨家率", "ratio"),
    FactorSpec("prior_market_failed_rate", "D-1炸板率", "ratio"),
    FactorSpec("prior_market_one_to_two_rate", "D-1一进二", "ratio"),
    FactorSpec("prior_market_two_to_three_rate", "D-1二进三", "ratio"),
    FactorSpec("auction_gap_pct", "竞价涨幅", "percent"),
    FactorSpec("prior_change_pct", "D-1个股涨幅", "percent"),
    FactorSpec("prior_return_5d_pct", "个股5日收益", "percent"),
    FactorSpec("prior_return_20d_pct", "个股20日收益", "percent"),
    FactorSpec("prior_turnover_rate", "D-1换手率", "percent"),
    FactorSpec("prior_amount_ratio_5d", "个股成交额/5日", "multiple"),
    FactorSpec("prior_amplitude_pct", "D-1振幅", "percent"),
)

OUTCOME_BUCKETS = (
    ("continuation_limit_up", "D+1继续涨停"),
    ("open_close_premium", "开盘与收盘均有溢价"),
    ("intraday_repair", "低开后修复"),
    ("high_open_fade", "高开后回落"),
    ("direct_breakdown", "D+1直接砸盘"),
    ("no_premium", "无溢价"),
)


def build_history_factor_audit(
    days: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
    exit_mode: str,
) -> dict[str, object]:
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"unsupported entry mode: {entry_mode}")
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")

    return_field = "next_open_return_pct" if exit_mode == "next_open" else "next_close_return_pct"
    samples = _closed_samples(days, entry_mode, return_field)
    factor_rows = [
        _factor_row(samples, spec)
        for spec in FACTOR_SPECS
    ]
    factor_rows.sort(key=_factor_rank_key)
    coverage = dict(days[-1].get("coverage") or {}) if days else {}

    return {
        "status": "ready" if samples else "insufficient_data",
        "mode": "point_in_time_factor_audit",
        "entry_mode": entry_mode,
        "exit_mode": exit_mode,
        "sample_scope": "top5_candidate_outcomes_not_fills",
        "selection_basis": "expanding_oos_only",
        "phase_summaries": {
            phase: _sample_summary(_phase_samples(samples, phase))
            for phase in AUDIT_PHASES
        },
        "outcome_buckets": {
            phase: _outcome_bucket_rows(_phase_samples(samples, phase))
            for phase in AUDIT_PHASES
        },
        "seal_summaries": {
            phase: _seal_rows(_phase_samples(samples, phase))
            for phase in AUDIT_PHASES
        },
        "market_phase_summaries": {
            phase: _market_phase_rows(_phase_samples(samples, phase))
            for phase in AUDIT_PHASES
        },
        "factors": factor_rows,
        "examples": _holdout_examples(samples, factor_rows),
        "coverage": {
            **coverage,
            "selected_start": days[0].get("trade_date") if days else None,
            "selected_end": days[-1].get("trade_date") if days else None,
            "selected_trade_days": len(days),
            "closed_candidate_count": len(samples),
        },
        "limitations": [
            "因子排序只使用滚动样本外区间；锁定留出集只验证方向，不参与排序。",
            "统计对象是逐日Top5候选的D+1结果，不代表盘口队列真实成交。",
            "当前行业归属来自现有成员快照，存在历史成员幸存者偏差。",
            "单因子关联不代表因果，也不能直接转换为买入阈值。",
        ],
    }


def _closed_samples(
    days: Sequence[Mapping[str, object]],
    entry_mode: str,
    return_field: str,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for day in days:
        phase = str(day.get("validation_phase") or "")
        if phase not in AUDIT_PHASES:
            continue
        lanes = day.get("lanes")
        lanes = lanes if isinstance(lanes, Mapping) else {}
        candidates = lanes.get(entry_mode)
        candidates = candidates if isinstance(candidates, list) else []
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            outcome = candidate.get("outcome")
            outcome = outcome if isinstance(outcome, Mapping) else {}
            return_pct = _number(outcome.get(return_field))
            if return_pct is None:
                continue
            known = candidate.get("known_at_signal")
            known = known if isinstance(known, Mapping) else {}
            samples.append(
                {
                    "candidate": candidate,
                    "known": known,
                    "outcome": outcome,
                    "phase": phase,
                    "return_pct": return_pct,
                    "is_win": return_pct > 0,
                    "outcome_code": _outcome_code(outcome),
                }
            )
    return samples


def _factor_row(samples: Sequence[Mapping[str, object]], spec: FactorSpec) -> dict[str, object]:
    expanding = _factor_stats(_phase_samples(samples, "expanding_oos"), spec.code)
    holdout = _factor_stats(_phase_samples(samples, "locked_holdout"), spec.code)
    status = _validation_status(expanding, holdout)
    return {
        "code": spec.code,
        "label": spec.label,
        "value_format": spec.value_format,
        "expanding_oos": expanding,
        "locked_holdout": holdout,
        "validation_status": status,
        "training_direction": expanding.get("direction"),
    }


def _factor_stats(samples: Sequence[Mapping[str, object]], code: str) -> dict[str, object]:
    values: list[tuple[float, bool]] = []
    for sample in samples:
        known = sample.get("known")
        known = known if isinstance(known, Mapping) else {}
        value = _number(known.get(code))
        if value is not None:
            values.append((value, bool(sample.get("is_win"))))
    winners = [value for value, is_win in values if is_win]
    losers = [value for value, is_win in values if not is_win]
    auc = _rank_auc(values)
    direction = "flat"
    if auc is not None and auc > 0.5:
        direction = "higher"
    elif auc is not None and auc < 0.5:
        direction = "lower"
    return {
        "sample_count": len(values),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "winner_median": _rounded(median(winners)) if winners else None,
        "loser_median": _rounded(median(losers)) if losers else None,
        "auc": _rounded(auc, 4),
        "effect_strength": _rounded(abs(auc - 0.5) * 200, 2) if auc is not None else None,
        "direction": direction,
    }


def _rank_auc(values: Sequence[tuple[float, bool]]) -> float | None:
    winner_count = sum(is_win for _, is_win in values)
    loser_count = len(values) - winner_count
    if not winner_count or not loser_count:
        return None
    ordered = sorted(values, key=lambda item: item[0])
    winner_rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2
        winner_rank_sum += average_rank * sum(is_win for _, is_win in ordered[index:end])
        index = end
    u_statistic = winner_rank_sum - winner_count * (winner_count + 1) / 2
    return u_statistic / (winner_count * loser_count)


def _validation_status(
    expanding: Mapping[str, object],
    holdout: Mapping[str, object],
) -> str:
    if not _sufficient_factor_sample(expanding, minimum_each=20):
        return "insufficient_training"
    training_effect = _number(expanding.get("effect_strength")) or 0.0
    if training_effect < 8 or expanding.get("direction") == "flat":
        return "no_clear_edge"
    if not _sufficient_factor_sample(holdout, minimum_each=8):
        return "insufficient_holdout"
    holdout_effect = _number(holdout.get("effect_strength")) or 0.0
    same_direction = holdout.get("direction") == expanding.get("direction")
    if same_direction and holdout_effect >= 4:
        return "confirmed"
    if same_direction:
        return "weak_confirm"
    if holdout_effect >= 4:
        return "reversed"
    return "inconclusive"


def _sufficient_factor_sample(stats: Mapping[str, object], *, minimum_each: int) -> bool:
    return (
        int(stats.get("winner_count") or 0) >= minimum_each
        and int(stats.get("loser_count") or 0) >= minimum_each
    )


def _factor_rank_key(row: Mapping[str, object]) -> tuple[float, str]:
    expanding = row.get("expanding_oos")
    expanding = expanding if isinstance(expanding, Mapping) else {}
    effect = _number(expanding.get("effect_strength"))
    return (-(effect if effect is not None else -1.0), str(row.get("code") or ""))


def _outcome_code(outcome: Mapping[str, object]) -> str:
    open_return = _number(outcome.get("next_open_return_pct"))
    close_return = _number(outcome.get("next_close_return_pct"))
    if _is_continuation_limit_up(outcome):
        return "continuation_limit_up"
    if (open_return is not None and open_return <= -5) or (
        close_return is not None and close_return <= -5
    ):
        return "direct_breakdown"
    if open_return is not None and close_return is not None:
        if open_return > 0 and close_return > 0:
            return "open_close_premium"
        if open_return <= 0 < close_return:
            return "intraday_repair"
        if open_return > 0 >= close_return:
            return "high_open_fade"
    return "no_premium"


def _is_continuation_limit_up(outcome: Mapping[str, object]) -> bool:
    if not bool(outcome.get("sealed")):
        return False
    entry_close = _number(outcome.get("entry_day_close_price"))
    next_close = _number(outcome.get("next_close_price"))
    if entry_close is None or next_close is None:
        return False
    return next_close >= main_board_limit_price(entry_close) - 0.005


def _outcome_bucket_rows(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    total = len(samples)
    rows: list[dict[str, object]] = []
    for code, label in OUTCOME_BUCKETS:
        subset = [sample for sample in samples if sample.get("outcome_code") == code]
        rows.append(
            {
                "code": code,
                "label": label,
                "count": len(subset),
                "share_pct": _rounded(len(subset) / total * 100, 2) if total else None,
                "average_return_pct": _average_return(subset),
            }
        )
    return rows


def _seal_rows(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows = []
    for sealed, label in ((True, "D日最终封住"), (False, "D日未封住")):
        subset = [
            sample
            for sample in samples
            if bool((sample.get("outcome") or {}).get("sealed")) is sealed
        ]
        rows.append({"code": "sealed" if sealed else "failed", "label": label, **_sample_summary(subset)})
    return rows


def _market_phase_rows(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    phases = sorted(
        {
            str((sample.get("known") or {}).get("prior_market_phase") or "unknown")
            for sample in samples
        }
    )
    return [
        {
            "phase": phase,
            **_sample_summary(
                [
                    sample
                    for sample in samples
                    if str((sample.get("known") or {}).get("prior_market_phase") or "unknown")
                    == phase
                ]
            ),
        }
        for phase in phases
    ]


def _sample_summary(samples: Sequence[Mapping[str, object]]) -> dict[str, object]:
    returns = [float(sample["return_pct"]) for sample in samples]
    return {
        "sample_count": len(returns),
        "win_count": sum(value > 0 for value in returns),
        "win_rate": _rounded(sum(value > 0 for value in returns) / len(returns) * 100, 2)
        if returns
        else None,
        "average_return_pct": _rounded(mean(returns)) if returns else None,
        "hard_loss_count": sum(value <= -5 for value in returns),
        "hard_loss_rate": _rounded(sum(value <= -5 for value in returns) / len(returns) * 100, 2)
        if returns
        else None,
    }


def _holdout_examples(
    samples: Sequence[Mapping[str, object]],
    factors: Sequence[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    holdout = _phase_samples(samples, "locked_holdout")
    winners = sorted(holdout, key=lambda sample: float(sample["return_pct"]), reverse=True)[:5]
    breakdowns = sorted(
        [sample for sample in holdout if float(sample["return_pct"]) <= -5],
        key=lambda sample: float(sample["return_pct"]),
    )[:5]
    factor_codes = [str(row.get("code")) for row in factors[:3]]
    return {
        "winners": [_example_row(sample, factor_codes) for sample in winners],
        "breakdowns": [_example_row(sample, factor_codes) for sample in breakdowns],
    }


def _example_row(sample: Mapping[str, object], factor_codes: Sequence[str]) -> dict[str, object]:
    candidate = sample.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    known = sample.get("known")
    known = known if isinstance(known, Mapping) else {}
    outcome = sample.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    return {
        "signal_date": candidate.get("signal_date"),
        "result_date": candidate.get("result_date"),
        "vt_symbol": candidate.get("vt_symbol"),
        "name": candidate.get("name"),
        "industry_name": candidate.get("industry_name") or known.get("prior_industry_name"),
        "target_board": candidate.get("target_board"),
        "rank": candidate.get("rank"),
        "return_pct": _rounded(_number(sample.get("return_pct"))),
        "outcome_code": sample.get("outcome_code"),
        "sealed": bool(outcome.get("sealed")),
        "touched": bool(outcome.get("touched")),
        "market_phase": known.get("prior_market_phase"),
        "factor_values": {code: _rounded(_number(known.get(code))) for code in factor_codes},
    }


def _phase_samples(
    samples: Sequence[Mapping[str, object]],
    phase: str,
) -> list[Mapping[str, object]]:
    return [sample for sample in samples if sample.get("phase") == phase]


def _average_return(samples: Sequence[Mapping[str, object]]) -> float | None:
    values = [float(sample["return_pct"]) for sample in samples]
    return _rounded(mean(values)) if values else None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _rounded(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None
