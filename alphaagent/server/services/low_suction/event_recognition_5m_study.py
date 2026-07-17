"""Five-minute recovery-transition study for event-recognized candidates."""

from __future__ import annotations

import bisect
import json
import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.execution import cash_ledger

from .event_recognition_falsification import (
    chronological_event_blocks,
    load_event_falsification_inputs,
)
from .event_recognition_minutes import (
    INTERVAL,
    REQUIRED_BARS,
    WINDOW_END,
    WINDOW_START,
    load_event_5m_manifest,
)
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash

STUDY_EVIDENCE_LEVEL = "event_recognition_5m_falsification"
FROZEN_RULES = (
    "vwap_reclaim",
    "open_reclaim",
    "previous_close_reclaim",
    "two_higher_closes_after_open_break",
)

INITIAL_CASH = 100_000.0
COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_BPS = 10.0
LOT_SIZE = 100

CANDIDATE_COLUMNS = (
    "event_id",
    "source_date",
    "entry_date",
    "planned_exit_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "recognition_rank",
    "signal_close",
    "active_direction",
    "danger_state",
    "market_phase",
)
MINUTE_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "bar_time",
    "interval",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "source",
)
DAILY_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)


def build_event_5m_state_panel(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate point-in-time states from complete candidate-only 5m days."""

    _require_columns(candidates, CANDIDATE_COLUMNS, "candidate")
    _require_columns(minute_bars, MINUTE_COLUMNS, "minute bar")
    candidate_frame = candidates.loc[:, list(CANDIDATE_COLUMNS)].copy()
    candidate_frame["source_date"] = pd.to_datetime(
        candidate_frame["source_date"], errors="raise"
    ).dt.date
    candidate_frame["entry_date"] = pd.to_datetime(
        candidate_frame["entry_date"], errors="raise"
    ).dt.date
    candidate_frame["planned_exit_date"] = pd.to_datetime(
        candidate_frame["planned_exit_date"], errors="raise"
    ).dt.date
    if candidate_frame.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("candidate 5m identities must be unique")

    bars = minute_bars.loc[minute_bars["interval"].eq(INTERVAL)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    bars["bar_time"] = pd.to_datetime(bars["bar_time"], errors="raise")
    if bars.duplicated(["vt_symbol", "bar_time", "interval"]).any():
        raise ValueError("candidate 5m bar timestamps must be unique")
    _validate_complete_minute_days(candidate_frame, bars)
    panel = candidate_frame.merge(
        bars,
        left_on=["vt_symbol", "entry_date"],
        right_on=["vt_symbol", "trade_date"],
        how="inner",
        validate="one_to_many",
    )
    panel = panel.sort_values(["event_id", "bar_time"], kind="stable").reset_index(
        drop=True
    )
    numeric = (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
        "signal_close",
    )
    for column in numeric:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    if panel[list(numeric)].isna().any().any():
        raise ValueError("candidate 5m prices, volume and turnover must be numeric")
    group = panel.groupby("event_id", sort=False)
    panel["cumulative_volume"] = group["volume"].cumsum()
    panel["cumulative_turnover"] = group["turnover"].cumsum()
    panel["vwap"] = panel["cumulative_turnover"] / panel["cumulative_volume"].where(
        panel["cumulative_volume"].gt(0)
    )
    panel["entry_day_open"] = group["open_price"].transform("first")
    panel["intraday_low"] = group["low_price"].cummin()
    panel["previous_bar_close"] = group["close_price"].shift(1)
    panel["two_bars_ago_close"] = group["close_price"].shift(2)
    panel["previous_bar_vwap"] = group["vwap"].shift(1)
    panel["next_bar_time"] = group["bar_time"].shift(-1)
    panel["next_bar_open"] = group["open_price"].shift(-1)

    panel["vwap_reclaim"] = (
        panel["previous_bar_close"].lt(panel["previous_bar_vwap"])
        & panel["close_price"].ge(panel["vwap"])
    )
    panel["open_reclaim"] = (
        panel["previous_bar_close"].lt(panel["entry_day_open"])
        & panel["close_price"].ge(panel["entry_day_open"])
    )
    panel["previous_close_reclaim"] = (
        panel["previous_bar_close"].lt(panel["signal_close"])
        & panel["close_price"].ge(panel["signal_close"])
    )
    panel["two_higher_closes_after_open_break"] = (
        panel["intraday_low"].lt(panel["entry_day_open"])
        & panel["close_price"].gt(panel["previous_bar_close"])
        & panel["previous_bar_close"].gt(panel["two_bars_ago_close"])
    )
    return panel


def extract_frozen_transitions(panel: pd.DataFrame) -> pd.DataFrame:
    """Emit the first executable transition for every candidate and frozen rule."""

    rows = []
    for rule in FROZEN_RULES:
        if rule not in panel:
            raise ValueError(f"missing frozen transition column: {rule}")
        eligible = panel.loc[
            panel[rule].astype(bool)
            & panel["next_bar_time"].notna()
            & panel["next_bar_open"].notna()
        ].copy()
        first = eligible.groupby("event_id", sort=False, as_index=False).first()
        for row in first.to_dict("records"):
            signal_time = pd.Timestamp(row["bar_time"]).to_pydatetime()
            transition_id = f"{int(row['event_id'])}:{rule}:{signal_time.isoformat()}"
            rows.append(
                {
                    "transition_id": transition_id,
                    "event_id": int(row["event_id"]),
                    "rule": rule,
                    "source_date": row["source_date"],
                    "entry_date": row["entry_date"],
                    "planned_exit_date": row["planned_exit_date"],
                    "sector_id": str(row["sector_id"]),
                    "concept_name": str(row["concept_name"]),
                    "cycle_id": str(row["cycle_id"]),
                    "vt_symbol": str(row["vt_symbol"]),
                    "recognition_rank": int(row["recognition_rank"]),
                    "previous_close": float(row["signal_close"]),
                    "active_direction": str(row["active_direction"]),
                    "danger_state": str(row["danger_state"]),
                    "market_phase": str(row["market_phase"]),
                    "signal_time": signal_time,
                    "entry_time": pd.Timestamp(row["next_bar_time"]).to_pydatetime(),
                    "entry_price_raw": float(row["next_bar_open"]),
                    "signal_close": float(row["close_price"]),
                    "signal_vwap": float(row["vwap"]),
                    "evidence_level": STUDY_EVIDENCE_LEVEL,
                }
            )
    return pd.DataFrame(rows, columns=_empty_transitions().columns).sort_values(
        ["source_date", "event_id", "rule"], kind="stable"
    ).reset_index(drop=True)


def execute_event_5m_transitions(
    transitions: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    cost_multiplier: float = 1.0,
) -> pd.DataFrame:
    _require_columns(transitions, tuple(_empty_transitions().columns), "transition")
    _require_columns(daily_bars, DAILY_COLUMNS, "daily bar")
    if transitions.empty:
        return _empty_outcomes()
    if cost_multiplier <= 0:
        raise ValueError("cost multiplier must be positive")
    calendar = tuple(sorted(set(pd.to_datetime(trading_dates).date)))
    bars = daily_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("daily bar identities must be unique")
    for column in ("open_price", "high_price", "low_price", "close_price", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    bars["previous_close"] = bars.groupby("vt_symbol", sort=False)["close_price"].shift(1)
    bar_index = {
        (str(row.vt_symbol), row.trade_date): row
        for row in bars.itertuples(index=False)
    }
    rows = [
        _execute_transition(
            transition,
            calendar=calendar,
            bar_index=bar_index,
            cost_multiplier=cost_multiplier,
        )
        for transition in transitions.to_dict("records")
    ]
    return pd.DataFrame(rows, columns=_empty_outcomes().columns)


def summarize_event_5m_outcomes(
    outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if outcomes.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    normal = outcomes.copy()
    stressed = stressed_outcomes.copy()
    normal["source_date"] = pd.to_datetime(normal["source_date"]).dt.date
    stressed["source_date"] = pd.to_datetime(stressed["source_date"]).dt.date
    dates = tuple(sorted(normal["source_date"].unique()))
    blocks = chronological_event_blocks(dates, block_count=min(5, len(dates)))
    normal = normal.merge(blocks, on="source_date", how="left", validate="many_to_one")
    stressed = stressed.merge(blocks, on="source_date", how="left", validate="many_to_one")

    block_rows = []
    for (rule, block), group in normal.groupby(["rule", "block"], sort=True):
        returns = _closed_returns(group)
        block_rows.append(
            {
                "rule": str(rule),
                "block": int(block),
                "source_days": int(group["source_date"].nunique()),
                "closed_trades": int(len(returns)),
                "win_rate_pct": _win_rate(returns),
                "mean_net_return_pct": _mean(returns),
                "profit_factor": _profit_factor(returns),
                "positive_block": bool(
                    len(returns)
                    and float(returns.mean()) > 0
                    and (_profit_factor(returns) or 0) > 1
                ),
            }
        )
    block_metrics = pd.DataFrame(block_rows)

    rule_rows = []
    for rule, group in normal.groupby("rule", sort=True):
        returns = _closed_returns(group)
        stressed_returns = _closed_returns(stressed.loc[stressed["rule"].eq(rule)])
        positive_blocks = int(
            block_metrics.loc[block_metrics["rule"].eq(rule), "positive_block"].sum()
        )
        win_rate = _win_rate(returns)
        mean_return = _mean(returns)
        profit_factor = _profit_factor(returns)
        double_mean = _mean(stressed_returns)
        qualified = bool(
            len(returns) >= 100
            and win_rate is not None
            and win_rate > 60
            and mean_return is not None
            and mean_return > 0
            and profit_factor is not None
            and profit_factor > 1
            and double_mean is not None
            and double_mean > 0
            and positive_blocks >= 4
        )
        rule_rows.append(
            {
                "rule": str(rule),
                "signals": int(len(group)),
                "closed_trades": int(len(returns)),
                "win_rate_pct": win_rate,
                "mean_net_return_pct": mean_return,
                "median_net_return_pct": _median(returns),
                "profit_factor": profit_factor,
                "tail_5pct": _quantile(returns, 0.05),
                "positive_blocks": positive_blocks,
                "double_cost_mean_net_return_pct": double_mean,
                "qualified_for_strict_retest": qualified,
            }
        )
    rule_metrics = pd.DataFrame(rule_rows)
    regime_metrics = _summarize_regimes(normal, stressed)
    return rule_metrics, block_metrics, regime_metrics


def load_event_5m_study_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    inputs = load_event_falsification_inputs()
    manifest = load_event_5m_manifest()
    incomplete = manifest.loc[manifest["status"].ne("complete")]
    if not incomplete.empty:
        raise ValueError("event 5m manifest must be complete before state research")
    candidates = inputs.candidates
    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique()))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.interval,
            schema.stock_minute_bars.c.open_price,
            schema.stock_minute_bars.c.high_price,
            schema.stock_minute_bars.c.low_price,
            schema.stock_minute_bars.c.close_price,
            schema.stock_minute_bars.c.volume,
            schema.stock_minute_bars.c.turnover,
            schema.stock_minute_bars.c.source,
        )
        .where(
            schema.stock_minute_bars.c.vt_symbol.in_(symbols),
            schema.stock_minute_bars.c.trade_date.between(dates[0], dates[-1]),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    minute_bars = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    panel = build_event_5m_state_panel(candidates, minute_bars)
    transitions = extract_frozen_transitions(panel)
    minute_fingerprint = fingerprint_frame(
        minute_bars,
        identity_columns=("vt_symbol", "bar_time", "interval"),
    ).as_dict()
    coverage = {
        "candidate_pairs": int(len(candidates)),
        "complete_pairs": int(manifest["status"].eq("complete").sum()),
        "minute_rows": int(len(minute_bars)),
        "transition_rows": int(len(transitions)),
        "transition_counts": {
            str(rule): int(count)
            for rule, count in transitions["rule"].value_counts().sort_index().items()
        },
        "discovery_end": inputs.discovery_end.isoformat(),
        "current_membership_rows_read": 0,
    }
    return transitions, inputs.stock_bars, {
        "coverage": coverage,
        "trading_dates": inputs.trading_dates,
        "minute_fingerprint": minute_fingerprint,
    }


def run_event_5m_state_study() -> dict[str, Any]:
    transitions, daily_bars, metadata = load_event_5m_study_data()
    normal = execute_event_5m_transitions(
        transitions,
        daily_bars,
        trading_dates=metadata["trading_dates"],
    )
    stressed = execute_event_5m_transitions(
        transitions,
        daily_bars,
        trading_dates=metadata["trading_dates"],
        cost_multiplier=2.0,
    )
    rule_metrics, block_metrics, regime_metrics = summarize_event_5m_outcomes(
        normal,
        stressed,
    )
    return build_event_5m_study_report(
        coverage=metadata["coverage"],
        rule_metrics=rule_metrics,
        block_metrics=block_metrics,
        regime_metrics=regime_metrics,
        minute_fingerprint=metadata["minute_fingerprint"],
    )


def build_event_5m_study_report(
    *,
    coverage: dict[str, Any],
    rule_metrics: pd.DataFrame,
    block_metrics: pd.DataFrame,
    regime_metrics: pd.DataFrame,
    minute_fingerprint: dict[str, Any] | str,
) -> dict[str, Any]:
    protocol = default_protocol()
    qualified = (
        rule_metrics.loc[rule_metrics["qualified_for_strict_retest"]]
        if not rule_metrics.empty
        else pd.DataFrame()
    )
    if not qualified.empty:
        conclusion = "worth_strict_retest"
    elif _has_direction_only(rule_metrics):
        conclusion = "event_5m_direction_only"
    else:
        conclusion = "no_event_5m_recovery_edge"
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "formal_metrics": None,
        "formal_rule_selected": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "frozen_rules": list(FROZEN_RULES),
        "coverage": coverage,
        "rule_metrics": _records(rule_metrics),
        "block_metrics": _records(block_metrics),
        "regime_diagnostics": _records(regime_metrics),
        "minute_fingerprint": minute_fingerprint,
        "qualifying_rules": (
            sorted(qualified["rule"].astype(str).tolist())
            if not qualified.empty
            else []
        ),
        "limitations": [
            "event-recognition candidates are not strict membership Top3",
            "five-minute bars cannot reconstruct tick queue priority",
            "all results remain inside the already-observed V2 discovery period",
            "formal cash compounding and outer holdout remain locked",
        ],
    }


def render_event_5m_study_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_event_5m_study_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# AlphaAgent Event-recognition 5m Recovery Study",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        "- Formal metrics: `null`",
        "- Holdout values read: `false`",
        f"- Candidate/complete pairs: `{coverage.get('candidate_pairs', 0)}/"
        f"{coverage.get('complete_pairs', 0)}`",
        f"- Minute/transition rows: `{coverage.get('minute_rows', 0)}/"
        f"{coverage.get('transition_rows', 0)}`",
        "",
        "| Rule | Signals | Closed | Win | Mean | Median | PF | Tail 5% | Positive blocks | Double-cost mean | Retest |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["rule_metrics"]:
        lines.append(
            f"| `{row['rule']}` | {row['signals']} | {row['closed_trades']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_pct(row['median_net_return_pct'])} | {_number(row['profit_factor'])} | "
            f"{_pct(row['tail_5pct'])} | {row['positive_blocks']}/5 | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} | "
            f"{'yes' if row['qualified_for_strict_retest'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "事件关系不是完整成员 Top3；本报告只允许否定或提名严格复测方向。",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_complete_minute_days(
    candidates: pd.DataFrame,
    bars: pd.DataFrame,
) -> None:
    expected_pairs = set(zip(candidates["vt_symbol"], candidates["entry_date"], strict=True))
    grouped = bars.groupby(["vt_symbol", "trade_date"], sort=False)
    actual_pairs = set(grouped.groups)
    missing_pairs = expected_pairs - actual_pairs
    if missing_pairs:
        raise ValueError("every candidate requires a complete 48-bar 5m day")
    for pair in expected_pairs:
        group = grouped.get_group(pair)
        if len(group) != REQUIRED_BARS or group["bar_time"].nunique() != REQUIRED_BARS:
            raise ValueError("every candidate requires exactly 48 unique 5m bars")
        times = group["bar_time"].dt.strftime("%H:%M")
        if times.min() != WINDOW_START or times.max() != WINDOW_END:
            raise ValueError("candidate 5m bars must span 09:35 through 15:00")


def _execute_transition(
    transition: dict[str, Any],
    *,
    calendar: tuple[date, ...],
    bar_index: dict[tuple[str, date], Any],
    cost_multiplier: float,
) -> dict[str, Any]:
    base = {**transition}
    base.update(
        {
            "actual_exit_date": None,
            "entry_price": None,
            "exit_price_raw": None,
            "exit_price": None,
            "volume": 0,
            "total_fees": None,
            "net_return_pct": None,
            "status": None,
            "reason": None,
            "cost_multiplier": float(cost_multiplier),
        }
    )
    raw_entry = float(transition["entry_price_raw"])
    previous_close = float(transition["previous_close"])
    if raw_entry >= previous_close * 1.10:
        base.update(status="rejected", reason="entry_at_limit_up")
        return base
    buy = cash_ledger.calculate_buy_execution(
        raw_price=raw_entry,
        cash=INITIAL_CASH,
        target_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        lot_size=LOT_SIZE,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
    )
    if buy.volume <= 0:
        base.update(status="rejected", reason="insufficient_cash")
        return base
    planned_exit = pd.Timestamp(transition["planned_exit_date"]).date()
    exit_bar = None
    actual_exit = None
    for exit_date in calendar[bisect.bisect_left(calendar, planned_exit) :]:
        row = bar_index.get((str(transition["vt_symbol"]), exit_date))
        if row is None or float(row.volume or 0) <= 0:
            continue
        previous = float(row.previous_close) if pd.notna(row.previous_close) else None
        if previous and _one_price_limit_down(row, previous):
            continue
        exit_bar = row
        actual_exit = exit_date
        break
    if exit_bar is None:
        base.update(status="unclosed", reason="no_sellable_exit_in_discovery")
        return base
    sell = cash_ledger.calculate_sell_execution(
        raw_price=float(exit_bar.close_price),
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        stamp_tax_rate=STAMP_TAX_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
    )
    final_cash = buy.cash_after + sell.cash_delta
    base.update(
        actual_exit_date=actual_exit,
        entry_price=buy.price,
        exit_price_raw=float(exit_bar.close_price),
        exit_price=sell.price,
        volume=buy.volume,
        total_fees=buy.fee + sell.fee,
        net_return_pct=(final_cash / INITIAL_CASH - 1.0) * 100.0,
        status="closed",
        reason=None,
    )
    return base


def _summarize_regimes(normal: pd.DataFrame, stressed: pd.DataFrame) -> pd.DataFrame:
    normal = normal.copy()
    stressed = stressed.copy()
    for frame in (normal, stressed):
        frame["regime_key"] = (
            frame["active_direction"].astype(str)
            + "/"
            + frame["danger_state"].astype(str)
        )
    rows = []
    for (rule, regime), group in normal.groupby(["rule", "regime_key"], sort=True):
        returns = _closed_returns(group)
        stressed_returns = _closed_returns(
            stressed.loc[
                stressed["rule"].eq(rule) & stressed["regime_key"].eq(regime)
            ]
        )
        rows.append(
            {
                "rule": str(rule),
                "regime_key": str(regime),
                "source_days": int(group["source_date"].nunique()),
                "closed_trades": int(len(returns)),
                "win_rate_pct": _win_rate(returns),
                "mean_net_return_pct": _mean(returns),
                "profit_factor": _profit_factor(returns),
                "double_cost_mean_net_return_pct": _mean(stressed_returns),
            }
        )
    return pd.DataFrame(rows)


def _has_direction_only(metrics: pd.DataFrame) -> bool:
    if metrics.empty:
        return False
    return bool(
        (
            metrics["closed_trades"].ge(100)
            & pd.to_numeric(metrics["mean_net_return_pct"], errors="coerce").gt(0)
            & pd.to_numeric(metrics["profit_factor"], errors="coerce").gt(1)
            & pd.to_numeric(
                metrics["double_cost_mean_net_return_pct"], errors="coerce"
            ).gt(0)
        ).any()
    )


def _one_price_limit_down(row: Any, previous_close: float) -> bool:
    limit_down = previous_close * 0.90
    tolerance = max(0.01, limit_down * 0.0015)
    return (
        float(row.high_price) <= limit_down + tolerance
        and float(row.close_price) <= limit_down + tolerance
    )


def _closed_returns(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(
        frame.loc[frame["status"].eq("closed"), "net_return_pct"], errors="coerce"
    ).dropna()


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values > 0].sum())
    losses = abs(float(values.loc[values < 0].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _win_rate(values: pd.Series) -> float | None:
    return float(values.gt(0).mean() * 100.0) if len(values) else None


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def _median(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


def _quantile(values: pd.Series, value: float) -> float | None:
    return float(values.quantile(value)) if len(values) else None


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: _json_value(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    return value


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _empty_transitions() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "transition_id",
            "event_id",
            "rule",
            "source_date",
            "entry_date",
            "planned_exit_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "recognition_rank",
            "previous_close",
            "active_direction",
            "danger_state",
            "market_phase",
            "signal_time",
            "entry_time",
            "entry_price_raw",
            "signal_close",
            "signal_vwap",
            "evidence_level",
        ]
    )


def _empty_outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *_empty_transitions().columns,
            "actual_exit_date",
            "entry_price",
            "exit_price_raw",
            "exit_price",
            "volume",
            "total_fees",
            "net_return_pct",
            "status",
            "reason",
            "cost_multiplier",
        ]
    )
