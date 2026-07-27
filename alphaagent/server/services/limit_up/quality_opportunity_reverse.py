"""Reverse-audit selected losses and missed D+1 limit-up opportunities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import inf

import pandas as pd

from alphaagent.server.services.limit_up import core_quality
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    monthly_summaries,
    performance_summary,
)


STUDY_VERSION = "limit-up-quality-opportunity-reverse-v1"
HIGH_RETURN_PCT = 5.0
HIGH_RETURN_SENSITIVITY_PCT = 8.0
TIME_SLICES = (
    ("2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("2026_01_02", date(2026, 1, 1), date(2026, 2, 28)),
    ("2026_03_07", date(2026, 3, 1), date(2026, 7, 31)),
)


def build_opportunity_reverse_frame(
    enriched_orders: Sequence[Mapping[str, object]],
    closed_trades: Sequence[Mapping[str, object]],
) -> pd.DataFrame:
    """Join closed independent-slot trades to signal-time order evidence."""

    orders: dict[tuple[date, str], dict[str, object]] = {}
    for raw_order in enriched_orders:
        identity = _identity(raw_order)
        if identity is None:
            continue
        if identity in orders:
            raise ValueError(f"duplicate order identity: {identity}")
        order = dict(raw_order)
        order.update(core_quality.ab_quality_gate(order))
        orders[identity] = order

    records: list[dict[str, object]] = []
    missing: list[str] = []
    for raw_trade in closed_trades:
        identity = _identity(raw_trade)
        order = orders.get(identity) if identity is not None else None
        if order is None:
            missing.append(
                f"{raw_trade.get('signal_date')}:{raw_trade.get('vt_symbol')}"
            )
            continue
        return_pct = _number(raw_trade.get("return_pct"))
        if return_pct is None:
            continue
        selected = order.get("core_quality_gate_passed") is True
        records.append(
            {
                **order,
                **dict(raw_trade),
                "trade_date": identity[0],
                "pool_rank": order.get("pool_rank") or 0,
                "return_pct": return_pct,
                "selected_ab": selected,
                "outcome_group": _outcome_group(selected, return_pct),
            }
        )
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(
            f"closed trade evidence missing for {len(missing)} rows: {preview}"
        )
    if not records:
        return pd.DataFrame()
    return (
        pd.DataFrame.from_records(records)
        .sort_values(["trade_date", "signal_time", "vt_symbol"], kind="stable")
        .reset_index(drop=True)
    )


def opportunity_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return outcome audit masks and prior-only rescue hypotheses."""

    selected = _boolean_series(frame, "selected_ab")
    returns = _numeric_series(frame, "return_pct")
    profitability = _boolean_series(frame, "profitability_gate_passed")
    recognition = _boolean_series(frame, "recognition_gate_passed")
    recognition_reason = _string_series(frame, "recognition_gate_reason")
    profitability_reason = _string_series(frame, "profitability_gate_reason")
    sample_count = _numeric_series(frame, "stock_d1_sample_count")
    combined_rate = _numeric_series(frame, "stock_gene_combined_win_rate")
    market_phase = _string_series(frame, "prior_market_phase")
    limit_count = _numeric_series(frame, "prior_limit_count_126")

    excluded = ~selected
    overtraded = recognition_reason.eq("prior_limit_count_126_above_6")
    return {
        "formal_pool": pd.Series(True, index=frame.index),
        "selected_ab": selected,
        "selected_loss": selected & returns.le(0),
        "selected_hard_loss": selected & returns.le(-5),
        "selected_high_return": selected & returns.ge(HIGH_RETURN_PCT),
        "excluded": excluded,
        "excluded_positive": excluded & returns.gt(0),
        "excluded_high_return": excluded & returns.ge(HIGH_RETURN_PCT),
        "excluded_high_return_8": excluded & returns.ge(HIGH_RETURN_SENSITIVITY_PCT),
        "profitability_pass_overtraded_market_repair": (
            excluded & profitability & overtraded & market_phase.eq("repair")
        ),
        "under_sampled_3_4_high_joint_recognition": (
            excluded
            & recognition
            & ~profitability
            & sample_count.between(3, 4)
            & combined_rate.ge(30)
        ),
        "low_joint_rate_with_recognition": (
            excluded
            & recognition
            & profitability_reason.eq("same_stock_joint_rate_below_30")
        ),
        "profitability_pass_overtraded": (excluded & profitability & limit_count.gt(6)),
    }


def evaluate_opportunity_reverse(frame: pd.DataFrame) -> dict[str, object]:
    """Evaluate fixed comparisons without selecting from outcome-only winners."""

    if frame.empty:
        return {}
    masks = opportunity_masks(frame)
    selected = frame.loc[masks["selected_ab"]]
    rescue = frame.loc[masks["profitability_pass_overtraded_market_repair"]]
    expanded = pd.concat([selected, rescue], ignore_index=True)
    grouped = attach_fixed_group_fields(frame)
    return {
        "study_version": STUDY_VERSION,
        "thresholds": {
            "high_return_pct": HIGH_RETURN_PCT,
            "high_return_sensitivity_pct": HIGH_RETURN_SENSITIVITY_PCT,
            "hard_loss_pct": -5.0,
        },
        "summaries": {
            name: performance_summary(frame.loc[mask], baseline_count=len(frame))
            for name, mask in masks.items()
        },
        "gate_matrix": _gate_matrix(frame),
        "feature_comparisons": {
            field: _selected_excluded_group_summaries(grouped, field)
            for field in _GROUP_FIELDS
        },
        "coverage": _coverage(frame, masks),
        "research_rescue": {
            "rule": (
                "profitability_gate_passed and prior_limit_count_126 > 6 "
                "and prior_market_phase == repair"
            ),
            "incremental": performance_summary(rescue, baseline_count=len(frame)),
            "combined_with_ab": performance_summary(
                expanded, baseline_count=len(frame)
            ),
            "incremental_time_slices": _time_slice_summaries(rescue),
            "incremental_monthly": monthly_summaries(rescue),
            "added_trade_days": len(
                set(rescue["trade_date"]) - set(selected["trade_date"])
            ),
        },
        "ledgers": _audit_ledgers(frame, masks),
    }


def evaluate_daily_proxy_rescue(frame: pd.DataFrame) -> dict[str, object]:
    """Falsify the formal rescue hypothesis on the daily-touch proxy."""

    if frame.empty:
        return {}
    normalized = frame.copy()
    normalized["signal_time"] = normalized.get(
        "signal_time", pd.Series(index=normalized.index, dtype=object)
    ).fillna("daily_proxy")
    normalized["pool_rank"] = normalized.get(
        "pool_rank", pd.Series(0, index=normalized.index)
    )
    pool_mask = _boolean_series(
        normalized, "daily_structural_eligible"
    ) & _boolean_series(normalized, "profitability_gate_passed")
    pool = normalized.loc[pool_mask].copy()
    rescue_mask = _numeric_series(pool, "prior_limit_count_126").gt(6) & _string_series(
        pool, "prior_market_phase"
    ).eq("repair")
    rescue = pool.loc[rescue_mask]
    real_event_start = date(2025, 6, 27)
    discovery_start = date(2026, 3, 1)
    dates = pd.to_datetime(rescue["trade_date"]).dt.date
    return {
        "pool": performance_summary(pool, baseline_count=len(pool)),
        "incremental": performance_summary(rescue, baseline_count=len(pool)),
        "before_real_event_coverage": performance_summary(
            rescue.loc[dates.lt(real_event_start)], baseline_count=len(pool)
        ),
        "observed_event_period": performance_summary(
            rescue.loc[dates.ge(real_event_start)], baseline_count=len(pool)
        ),
        "before_discovery": performance_summary(
            rescue.loc[dates.lt(discovery_start)], baseline_count=len(pool)
        ),
        "by_year": {
            str(year): performance_summary(rows, baseline_count=len(pool))
            for year, rows in rescue.groupby(
                pd.to_datetime(rescue["trade_date"]).dt.year, sort=True
            )
        },
        "by_lane": {
            str(lane): performance_summary(rows, baseline_count=len(pool))
            for lane, rows in rescue.groupby("lane", sort=True)
        },
        "monthly": monthly_summaries(rescue),
    }


_GROUP_FIELDS = (
    "lane",
    "prior_market_phase",
    "signal_kind",
    "signal_time_bucket",
    "prior_limit_count_bin",
    "stock_d1_sample_bin",
    "stock_gene_joint_rate_bin",
    "industry_turnover_bin",
    "industry_sealed_bin",
    "industry_leader_rank_bin",
    "stock_amount_ratio_bin",
)


def attach_fixed_group_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach predeclared, interpretable bins used by the reverse audit."""

    result = frame.copy()
    result["signal_time_bucket"] = _string_series(result, "signal_time").map(
        _signal_time_bucket
    )
    result["prior_limit_count_bin"] = _bins(
        result,
        "prior_limit_count_126",
        [-inf, 1, 3, 6, 9, inf],
        ["<=1", "2-3", "4-6", "7-9", "10+"],
    )
    result["stock_d1_sample_bin"] = _bins(
        result, "stock_d1_sample_count", [-inf, 2, 4, inf], ["0-2", "3-4", "5+"]
    )
    result["stock_gene_joint_rate_bin"] = _bins(
        result,
        "stock_gene_combined_win_rate",
        [-inf, 15, 30, 50, inf],
        ["<15", "15-<30", "30-<50", "50+"],
        right=False,
    )
    result["industry_turnover_bin"] = _bins(
        result,
        "prior_industry_turnover_ratio_5d",
        [-inf, 0.8, 1, 1.2, inf],
        ["<0.8", "0.8-<1", "1-<1.2", "1.2+"],
        right=False,
    )
    result["industry_sealed_bin"] = _bins(
        result, "prior_industry_sealed_count", [-inf, 0, 1, inf], ["0", "1", "2+"]
    )
    result["industry_leader_rank_bin"] = _bins(
        result,
        "prior_industry_leader_rank",
        [-inf, 3, 10, 30, inf],
        ["top3", "4-10", "11-30", "31+"],
    )
    result["stock_amount_ratio_bin"] = _bins(
        result,
        "prior_amount_ratio_5d",
        [-inf, 0.8, 1, 1.5, inf],
        ["<0.8", "0.8-<1", "1-<1.5", "1.5+"],
        right=False,
    )
    return result


def _gate_matrix(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    profitability = _boolean_series(frame, "profitability_gate_passed")
    recognition = _boolean_series(frame, "recognition_gate_passed")
    masks = {
        "both_pass_ab": profitability & recognition,
        "profitability_fail_recognition_pass": ~profitability & recognition,
        "profitability_pass_recognition_fail": profitability & ~recognition,
        "both_fail": ~profitability & ~recognition,
    }
    return {
        name: performance_summary(frame.loc[mask], baseline_count=len(frame))
        for name, mask in masks.items()
    }


def _selected_excluded_group_summaries(
    frame: pd.DataFrame,
    field: str,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    raw_values = frame.get(
        field, pd.Series("unavailable", index=frame.index, dtype=object)
    )
    values = raw_values.astype(object).where(raw_values.notna(), "unavailable")
    for value in sorted(values.unique(), key=str):
        rows = frame.loc[values.eq(value)]
        result[str(value)] = {
            "selected_ab": performance_summary(rows.loc[rows["selected_ab"]]),
            "excluded": performance_summary(rows.loc[~rows["selected_ab"]]),
        }
    return result


def _coverage(
    frame: pd.DataFrame,
    masks: Mapping[str, pd.Series],
) -> dict[str, object]:
    selected_dates = set(frame.loc[masks["selected_ab"], "trade_date"])
    high_dates = set(frame.loc[masks["excluded_high_return"], "trade_date"])
    loss_dates = set(frame.loc[masks["selected_loss"], "trade_date"])
    all_dates = set(frame["trade_date"])
    return {
        "closed_trade_count": len(frame),
        "candidate_trade_days": len(all_dates),
        "selected_trade_days": len(selected_dates),
        "unselected_trade_days": len(all_dates - selected_dates),
        "unselected_days_with_high_return": len(high_dates - selected_dates),
        "selected_loss_days": len(loss_dates),
        "selected_loss_days_with_excluded_high_return": len(loss_dates & high_dates),
    }


def _audit_ledgers(
    frame: pd.DataFrame,
    masks: Mapping[str, pd.Series],
) -> dict[str, list[dict[str, object]]]:
    selected_dates = set(frame.loc[masks["selected_ab"], "trade_date"])
    loss_dates = set(frame.loc[masks["selected_loss"], "trade_date"])
    high = frame.loc[masks["excluded_high_return"]].copy()
    no_trade = high.loc[~high["trade_date"].isin(selected_dates)]
    same_day = high.loc[high["trade_date"].isin(loss_dates)]
    return {
        "selected_losses": _ledger_records(frame.loc[masks["selected_loss"]]),
        "same_day_excluded_high_return": _ledger_records(same_day),
        "no_trade_day_top_high_return": _ledger_records(
            no_trade.sort_values("return_pct", ascending=False)
            .groupby("trade_date", sort=True)
            .head(1)
        ),
        "research_rescue": _ledger_records(
            frame.loc[masks["profitability_pass_overtraded_market_repair"]]
        ),
    }


def _ledger_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    fields = (
        "trade_date",
        "name",
        "vt_symbol",
        "lane",
        "signal_time",
        "return_pct",
        "core_quality_gate_reason",
        "profitability_gate_reason",
        "recognition_gate_reason",
        "prior_limit_count_126",
        "stock_d1_sample_count",
        "stock_gene_combined_win_rate",
        "prior_industry_turnover_ratio_5d",
        "prior_market_phase",
        "prior_industry_leader_rank",
        "prior_industry_sealed_count",
    )
    available = [field for field in fields if field in frame]
    return frame.sort_values(["trade_date", "return_pct"], ascending=[True, False])[
        available
    ].to_dict("records")


def _time_slice_summaries(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    return {
        label: performance_summary(frame.loc[dates.between(start, end)])
        for label, start, end in TIME_SLICES
    }


def _outcome_group(selected: bool, return_pct: float) -> str:
    prefix = "selected" if selected else "excluded"
    if return_pct >= HIGH_RETURN_PCT:
        return f"{prefix}_high_return"
    if return_pct > 0:
        return f"{prefix}_positive"
    return f"{prefix}_loss"


def _identity(candidate: Mapping[str, object]) -> tuple[date, str] | None:
    trade_date = _as_date(
        candidate.get("signal_date")
        or candidate.get("entry_date")
        or candidate.get("buy_date")
        or candidate.get("trade_date")
    )
    symbol = str(candidate.get("vt_symbol") or "")
    return (trade_date, symbol) if trade_date is not None and symbol else None


def _signal_time_bucket(value: object) -> str:
    text = str(value or "")
    if text < "10:30:00":
        return "10:00-10:30"
    if text < "11:30:00":
        return "10:30-11:30"
    if text < "14:00:00":
        return "13:00-14:00"
    return "14:00-14:30"


def _bins(
    frame: pd.DataFrame,
    field: str,
    bins: Sequence[float],
    labels: Sequence[str],
    *,
    right: bool = True,
) -> pd.Series:
    return pd.cut(
        _numeric_series(frame, field),
        bins=bins,
        labels=labels,
        right=right,
    )


def _numeric_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(
        frame.get(field, pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )


def _string_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return (
        frame.get(field, pd.Series("", index=frame.index, dtype=object))
        .fillna("")
        .astype(str)
    )


def _boolean_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series(False, index=frame.index, dtype=bool)).eq(True)


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and pd.notna(number) else None
