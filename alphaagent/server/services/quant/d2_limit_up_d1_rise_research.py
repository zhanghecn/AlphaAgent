"""Event study for a D-2 limit-up followed by a positive non-limit D-1."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.db.session import get_engine, is_database_configured


DEFAULT_COMMISSION_RATE = 0.0003
DEFAULT_STAMP_TAX_RATE = 0.0005
DEFAULT_SLIPPAGE_BPS = 10.0
DEFAULT_TOTAL_COST_RATE = (
    DEFAULT_COMMISSION_RATE * 2
    + DEFAULT_STAMP_TAX_RATE
    + DEFAULT_SLIPPAGE_BPS * 2 / 10_000
)
MIN_COMPLETE_MARKET_SYMBOLS = 3_000
MAX_VALID_MAIN_BOARD_RETURN_PCT = 11.5

REQUIRED_DAILY_COLUMNS = (
    "vt_symbol",
    "name",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
)

EVENT_COLUMNS = (
    "vt_symbol",
    "name",
    "d2_date",
    "entry_date",
    "outcome_date",
    "d2_close_price",
    "d2_limit_price",
    "entry_price",
    "d1_limit_price",
    "d1_return_pct",
    "d_open_price",
    "d_high_price",
    "d_low_price",
    "d_close_price",
    "gross_open_return_pct",
    "gross_high_return_pct",
    "gross_low_return_pct",
    "gross_close_return_pct",
    "net_close_return_pct",
    "market_return_pct",
    "excess_close_return_pct",
    "d_close_limit_up",
    "outcome_data_valid",
)

SUMMARY_REQUIRED_COLUMNS = (
    "vt_symbol",
    "name",
    "entry_date",
    "outcome_date",
    "d1_return_pct",
    "gross_open_return_pct",
    "gross_high_return_pct",
    "gross_low_return_pct",
    "gross_close_return_pct",
    "net_close_return_pct",
    "market_return_pct",
    "excess_close_return_pct",
    "d_close_limit_up",
)


def main_board_limit_price(previous_close: float) -> float:
    """Return the 10% price limit with exchange-style half-up cent rounding."""

    price = Decimal(str(previous_close)) * Decimal("1.10")
    return float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_event_frame(
    daily_bars: pd.DataFrame,
    *,
    total_cost_rate: float = DEFAULT_TOTAL_COST_RATE,
) -> pd.DataFrame:
    """Build point-in-time D-1 signals and attach D outcome labels."""

    _validate_daily_columns(daily_bars)
    if total_cost_rate < 0:
        raise ValueError("total_cost_rate must be non-negative")
    if daily_bars.empty:
        return _empty_event_frame(total_cost_rate=total_cost_rate)

    frame = daily_bars.loc[:, REQUIRED_DAILY_COLUMNS].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    for column in ("open_price", "high_price", "low_price", "close_price"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(
        subset=["vt_symbol", "name", "trade_date", "open_price", "high_price", "low_price", "close_price"],
        inplace=True,
    )
    input_row_count = len(frame)
    frame = frame[_eligible_main_board_mask(frame)].copy()
    frame.sort_values(["vt_symbol", "trade_date"], inplace=True)
    frame.drop_duplicates(["vt_symbol", "trade_date"], keep="last", inplace=True)
    eligible_row_count = len(frame)
    if frame.empty:
        return _empty_event_frame(
            total_cost_rate=total_cost_rate,
            input_row_count=input_row_count,
            eligible_row_count=0,
        )

    available_start = frame["trade_date"].min()
    available_end = frame["trade_date"].max()
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["previous_trade_date"] = grouped["trade_date"].shift(1)
    frame["previous_close"] = grouped["close_price"].shift(1)
    frame["next_trade_date"] = grouped["trade_date"].shift(-1)
    for column in ("open_price", "high_price", "low_price", "close_price"):
        frame[f"next_{column}"] = grouped[column].shift(-1)

    frame["limit_price"] = _limit_price_series(frame["previous_close"])
    frame["is_limit_up_close"] = np.isclose(
        frame["close_price"],
        frame["limit_price"],
        atol=0.005,
        rtol=0.0,
        equal_nan=False,
    )
    frame["previous_was_limit_up"] = grouped["is_limit_up_close"].shift(1).eq(True)
    frame["d1_return_pct"] = (frame["close_price"] / frame["previous_close"] - 1.0) * 100.0
    frame["d1_high_return_pct"] = (frame["high_price"] / frame["previous_close"] - 1.0) * 100.0
    frame["d1_low_return_pct"] = (frame["low_price"] / frame["previous_close"] - 1.0) * 100.0

    global_previous, global_next = _global_day_maps(frame["trade_date"])
    frame["global_previous_trade_date"] = frame["trade_date"].map(global_previous)
    frame["global_next_trade_date"] = frame["trade_date"].map(global_next)
    has_continuous_pattern = (
        frame["previous_trade_date"].eq(frame["global_previous_trade_date"])
        & frame["next_trade_date"].eq(frame["global_next_trade_date"])
    )

    frame["gross_forward_close_return_pct"] = (
        frame["next_close_price"] / frame["close_price"] - 1.0
    ) * 100.0
    valid_market_forward = (
        frame["next_trade_date"].eq(frame["global_next_trade_date"])
        & frame["gross_forward_close_return_pct"].between(
            -MAX_VALID_MAIN_BOARD_RETURN_PCT,
            MAX_VALID_MAIN_BOARD_RETURN_PCT,
        )
    )
    market_returns = (
        frame.loc[valid_market_forward]
        .groupby("trade_date")["gross_forward_close_return_pct"]
        .mean()
    )
    frame["market_return_pct"] = frame["trade_date"].map(market_returns)

    signal_mask = (
        has_continuous_pattern
        & frame["previous_was_limit_up"]
        & frame["d1_return_pct"].gt(0.0)
        & frame["d1_return_pct"].le(MAX_VALID_MAIN_BOARD_RETURN_PCT)
        & frame["d1_high_return_pct"].le(MAX_VALID_MAIN_BOARD_RETURN_PCT)
        & frame["d1_low_return_pct"].ge(-MAX_VALID_MAIN_BOARD_RETURN_PCT)
        & ~frame["is_limit_up_close"]
        & frame["close_price"].gt(0.0)
        & frame["next_close_price"].gt(0.0)
    )
    signals = frame.loc[signal_mask].copy()
    if signals.empty:
        return _empty_event_frame(
            total_cost_rate=total_cost_rate,
            input_row_count=input_row_count,
            eligible_row_count=eligible_row_count,
            available_start=available_start,
            available_end=available_end,
            available_day_count=int(frame["trade_date"].nunique()),
        )

    signals["gross_open_return_pct"] = _forward_return(signals["close_price"], signals["next_open_price"])
    signals["gross_high_return_pct"] = _forward_return(signals["close_price"], signals["next_high_price"])
    signals["gross_low_return_pct"] = _forward_return(signals["close_price"], signals["next_low_price"])
    signals["gross_close_return_pct"] = signals["gross_forward_close_return_pct"]
    signals["net_close_return_pct"] = signals["gross_close_return_pct"] - total_cost_rate * 100.0
    signals["excess_close_return_pct"] = signals["gross_close_return_pct"] - signals["market_return_pct"]
    outcome_path_columns = (
        "gross_open_return_pct",
        "gross_high_return_pct",
        "gross_low_return_pct",
        "gross_close_return_pct",
    )
    signals["outcome_data_valid"] = signals.loc[:, outcome_path_columns].apply(
        lambda values: values.between(
            -MAX_VALID_MAIN_BOARD_RETURN_PCT,
            MAX_VALID_MAIN_BOARD_RETURN_PCT,
        ).all(),
        axis=1,
    )
    signals["next_limit_price"] = _limit_price_series(signals["close_price"])
    signals["d_close_limit_up"] = np.isclose(
        signals["next_close_price"],
        signals["next_limit_price"],
        atol=0.005,
        rtol=0.0,
        equal_nan=False,
    )

    events = pd.DataFrame(
        {
            "vt_symbol": signals["vt_symbol"],
            "name": signals["name"],
            "d2_date": signals["previous_trade_date"],
            "entry_date": signals["trade_date"],
            "outcome_date": signals["next_trade_date"],
            "d2_close_price": signals["previous_close"],
            "d2_limit_price": grouped["limit_price"].shift(1).loc[signals.index],
            "entry_price": signals["close_price"],
            "d1_limit_price": signals["limit_price"],
            "d1_return_pct": signals["d1_return_pct"],
            "d_open_price": signals["next_open_price"],
            "d_high_price": signals["next_high_price"],
            "d_low_price": signals["next_low_price"],
            "d_close_price": signals["next_close_price"],
            "gross_open_return_pct": signals["gross_open_return_pct"],
            "gross_high_return_pct": signals["gross_high_return_pct"],
            "gross_low_return_pct": signals["gross_low_return_pct"],
            "gross_close_return_pct": signals["gross_close_return_pct"],
            "net_close_return_pct": signals["net_close_return_pct"],
            "market_return_pct": signals["market_return_pct"],
            "excess_close_return_pct": signals["excess_close_return_pct"],
            "d_close_limit_up": signals["d_close_limit_up"],
            "outcome_data_valid": signals["outcome_data_valid"],
        }
    ).sort_values(["entry_date", "vt_symbol"], ignore_index=True)
    events.attrs.update(
        {
            "total_cost_rate": total_cost_rate,
            "input_row_count": input_row_count,
            "eligible_row_count": eligible_row_count,
            "available_start": available_start,
            "available_end": available_end,
            "available_day_count": int(frame["trade_date"].nunique()),
        }
    )
    return events


def summarize_event_frame(events: pd.DataFrame) -> dict[str, object]:
    """Summarize per-trade D outcomes and equal-weight daily compounding."""

    total_cost_rate = float(events.attrs.get("total_cost_rate", DEFAULT_TOTAL_COST_RATE))
    if events.empty:
        return _empty_report(events, total_cost_rate=total_cost_rate)
    _validate_event_columns(events)

    all_events = events.copy()
    all_events["entry_date"] = pd.to_datetime(all_events["entry_date"], errors="coerce").dt.normalize()
    all_events["outcome_date"] = pd.to_datetime(all_events["outcome_date"], errors="coerce").dt.normalize()
    all_events.sort_values(["entry_date", "vt_symbol"], inplace=True)
    valid_outcome = (
        all_events["outcome_data_valid"].fillna(False).astype(bool)
        if "outcome_data_valid" in all_events
        else pd.Series(True, index=all_events.index)
    )
    ordered = all_events.loc[valid_outcome].copy()
    if ordered.empty:
        report = _empty_report(events, total_cost_rate=total_cost_rate)
        report["dataset"].update(
            {
                "signal_count": len(all_events),
                "excluded_outcome_count": len(all_events),
            }
        )
        return report

    gross_metrics = _return_metrics(ordered["gross_close_return_pct"])
    net_metrics = _return_metrics(ordered["net_close_return_pct"])
    excess_metrics = _return_metrics(ordered["excess_close_return_pct"])
    trade_summary = {
        "sample_count": len(ordered),
        "gross_win_rate_pct": gross_metrics["win_rate_pct"],
        "gross_average_return_pct": gross_metrics["average_return_pct"],
        "gross_median_return_pct": gross_metrics["median_return_pct"],
        "gross_profit_factor": gross_metrics["profit_factor"],
        "net_win_rate_pct": net_metrics["win_rate_pct"],
        "net_average_return_pct": net_metrics["average_return_pct"],
        "net_median_return_pct": net_metrics["median_return_pct"],
        "net_profit_factor": net_metrics["profit_factor"],
        "average_market_return_pct": _round(ordered["market_return_pct"].mean()),
        "average_excess_return_pct": excess_metrics["average_return_pct"],
        "positive_excess_rate_pct": excess_metrics["win_rate_pct"],
        "d_close_limit_up_rate_pct": _round(ordered["d_close_limit_up"].fillna(False).mean() * 100.0),
    }
    path_summary = {
        label: _return_metrics(ordered[column])
        for label, column in (
            ("d_open", "gross_open_return_pct"),
            ("d_high", "gross_high_return_pct"),
            ("d_low", "gross_low_return_pct"),
            ("d_close", "gross_close_return_pct"),
        )
    }
    daily_results, portfolio = _portfolio_summary(ordered)
    by_year = []
    for year, subset in ordered.groupby(ordered["entry_date"].dt.year, sort=True):
        _, year_portfolio = _portfolio_summary(subset)
        year_gross = _return_metrics(subset["gross_close_return_pct"])
        year_net = _return_metrics(subset["net_close_return_pct"])
        by_year.append(
            {
                "year": int(year),
                "sample_count": len(subset),
                "signal_day_count": int(subset["entry_date"].nunique()),
                "gross_win_rate_pct": year_gross["win_rate_pct"],
                "gross_average_return_pct": year_gross["average_return_pct"],
                "net_win_rate_pct": year_net["win_rate_pct"],
                "net_average_return_pct": year_net["average_return_pct"],
                "net_compound_return_pct": year_portfolio["net_compound_return_pct"],
                "net_max_drawdown_pct": year_portfolio["net_max_drawdown_pct"],
            }
        )

    dataset = {
        "input_row_count": int(events.attrs.get("input_row_count", len(events))),
        "eligible_row_count": int(events.attrs.get("eligible_row_count", len(events))),
        "complete_trading_day_count": int(events.attrs.get("available_day_count", 0)),
        "signal_count": len(all_events),
        "excluded_outcome_count": len(all_events) - len(ordered),
        "sample_count": len(ordered),
        "symbol_count": int(ordered["vt_symbol"].nunique()),
        "signal_day_count": int(ordered["entry_date"].nunique()),
        "available_start_date": _date_text(events.attrs.get("available_start")),
        "available_end_date": _date_text(events.attrs.get("available_end")),
        "first_entry_date": _date_text(ordered["entry_date"].min()),
        "last_entry_date": _date_text(ordered["entry_date"].max()),
        "last_outcome_date": _date_text(ordered["outcome_date"].max()),
    }
    return {
        "status": "ready",
        "dataset": dataset,
        "costs": _cost_payload(total_cost_rate),
        "trade_summary": trade_summary,
        "path_summary": path_summary,
        "portfolio": portfolio,
        "by_year": by_year,
        "daily_results": daily_results,
        "samples": {
            "best": _sample_records(ordered.nlargest(10, "gross_close_return_pct")),
            "worst": _sample_records(ordered.nsmallest(10, "gross_close_return_pct")),
        },
        "limitations": _limitations(),
    }


def run_d2_limit_up_d1_rise_research(
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, object]:
    """Run the event study against the configured AlphaAgent database."""

    if not is_database_configured():
        raise RuntimeError("DATABASE_URL is not configured")
    daily_bars = _load_daily_bars(start=start, end=end)
    events = build_event_frame(daily_bars)
    report = summarize_event_frame(events)
    _validate_real_report(events, report)
    return report


def render_markdown_report(report: Mapping[str, object]) -> str:
    """Render the reproducible evidence report in Chinese."""

    dataset = _mapping(report.get("dataset"))
    costs = _mapping(report.get("costs"))
    trade = _mapping(report.get("trade_summary"))
    portfolio = _mapping(report.get("portfolio"))
    path = _mapping(report.get("path_summary"))
    lines = [
        "# D-2 涨停、D-1 续涨事件研究",
        "",
        "## 研究定义",
        "",
        "- 股票池：沪深主板、当前名称非 ST/退市/新股状态。",
        "- D-2：按前收盘价计算的 10cm 涨停价，且收盘封住涨停。",
        "- D-1：收涨但未涨停，按收盘价买入。",
        "- D：以收盘卖出为主口径，同时观察开盘、最高、最低路径。",
        "- 复利：同一信号日全部样本等权，再按日期连乘；无信号时持有现金。",
        "",
        "## 数据覆盖",
        "",
        f"- 原始日线：`{dataset.get('input_row_count', 0)}` 行；合格主板日线：`{dataset.get('eligible_row_count', 0)}` 行。",
        f"- 可用区间：`{dataset.get('available_start_date')}` 至 `{dataset.get('available_end_date')}`，共 `{dataset.get('complete_trading_day_count', 0)}` 个完整交易日。",
        f"- 事件区间：`{dataset.get('first_entry_date')}` 至 `{dataset.get('last_outcome_date')}`。",
        f"- 形态信号：`{dataset.get('signal_count', 0)}` 笔；剔除异常结果 `"
        f"{dataset.get('excluded_outcome_count', 0)}` 笔；有效样本 `{dataset.get('sample_count', 0)}` 笔。",
        f"- 有效样本覆盖：`{dataset.get('symbol_count', 0)}` 只股票，`{dataset.get('signal_day_count', 0)}` 个信号日。",
        "",
        "## D 日结果",
        "",
        "| 口径 | 胜率 | 平均收益 | 中位收益 | 利润因子 |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| 毛收益 | {_pct(trade.get('gross_win_rate_pct'))} | {_pct(trade.get('gross_average_return_pct'))} | {_pct(trade.get('gross_median_return_pct'))} | {_number(trade.get('gross_profit_factor'))} |",
        f"| 扣费后 | {_pct(trade.get('net_win_rate_pct'))} | {_pct(trade.get('net_average_return_pct'))} | {_pct(trade.get('net_median_return_pct'))} | {_number(trade.get('net_profit_factor'))} |",
        "",
        f"- 同期同日主板等权平均收益：`{_pct(trade.get('average_market_return_pct'))}`。",
        f"- 形态平均超额收益：`{_pct(trade.get('average_excess_return_pct'))}`；跑赢同日市场比例：`{_pct(trade.get('positive_excess_rate_pct'))}`。",
        f"- D 日收盘继续涨停比例：`{_pct(trade.get('d_close_limit_up_rate_pct'))}`。",
        "",
        "## D 日价格路径",
        "",
        "| 价格 | 正收益比例 | 平均收益 | 中位收益 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, title in (("d_open", "开盘"), ("d_high", "最高"), ("d_low", "最低"), ("d_close", "收盘")):
        metric = _mapping(path.get(label))
        lines.append(
            f"| {title} | {_pct(metric.get('win_rate_pct'))} | {_pct(metric.get('average_return_pct'))} | {_pct(metric.get('median_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## 同日等权复利",
            "",
            f"- 毛复利：`{_pct(portfolio.get('gross_compound_return_pct'))}`；扣费后复利：`{_pct(portfolio.get('net_compound_return_pct'))}`。",
            f"- 扣费后期末净值倍数：`{_number(portfolio.get('net_ending_equity_multiple'))}`；年化代理：`{_pct(portfolio.get('net_annualized_return_pct'))}`。",
            f"- 扣费后最大回撤：`{_pct(portfolio.get('net_max_drawdown_pct'))}`；盈利信号日比例：`{_pct(portfolio.get('net_profitable_signal_day_rate_pct'))}`。",
            f"- 平均同日持仓：`{_number(portfolio.get('average_positions_per_signal_day'))}`；最大同日持仓：`{portfolio.get('max_positions_per_signal_day')}`。",
            f"- 默认往返成本：`{_pct(costs.get('total_round_trip_cost_pct'))}`，含双边佣金、卖出印花税和双边滑点。",
            "",
            "## 年度稳定性",
            "",
            "| 年份 | 样本 | 信号日 | 净胜率 | 净均值 | 净复利 | 最大回撤 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("by_year") or []:
        item = _mapping(row)
        lines.append(
            f"| {item.get('year')} | {item.get('sample_count')} | {item.get('signal_day_count')} | "
            f"{_pct(item.get('net_win_rate_pct'))} | {_pct(item.get('net_average_return_pct'))} | "
            f"{_pct(item.get('net_compound_return_pct'))} | {_pct(item.get('net_max_drawdown_pct'))} |"
        )
    lines.extend(["", "## 最好与最差样本", ""])
    for key, title in (("best", "最好 10 笔"), ("worst", "最差 10 笔")):
        lines.extend(
            [
                f"### {title}",
                "",
                "| D-1 | 股票 | D-1 涨幅 | D 收盘毛收益 | D 收盘净收益 |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for row in _mapping(report.get("samples")).get(key, []):
            item = _mapping(row)
            lines.append(
                f"| {item.get('entry_date')} | {item.get('name')} `{item.get('vt_symbol')}` | "
                f"{_pct(item.get('d1_return_pct'))} | {_pct(item.get('gross_close_return_pct'))} | "
                f"{_pct(item.get('net_close_return_pct'))} |"
            )
        lines.append("")
    lines.extend(["## 限制", ""])
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    return "\n".join(lines).rstrip() + "\n"


def _load_daily_bars(*, start: date | None, end: date | None) -> pd.DataFrame:
    where = [
        "((split_part(b.vt_symbol, '.', 2) = 'SSE' "
        "and left(b.vt_symbol, 3) in ('600', '601', '603', '605')) or "
        "(split_part(b.vt_symbol, '.', 2) = 'SZSE' "
        "and left(b.vt_symbol, 3) in ('000', '001', '002', '003'))) ",
        "b.trade_date in ("
        "select trade_date from stock_daily_bars "
        f"group by trade_date having count(distinct vt_symbol) >= {MIN_COMPLETE_MARKET_SYMBOLS}"
        ")",
    ]
    params: dict[str, object] = {}
    if start is not None:
        where.append("b.trade_date >= %(start)s")
        params["start"] = start
    if end is not None:
        where.append("b.trade_date <= %(end)s")
        params["end"] = end
    sql = f"""
    select
        b.vt_symbol,
        s.name,
        b.trade_date,
        b.open_price,
        b.high_price,
        b.low_price,
        b.close_price
    from stock_daily_bars b
    join stocks s on s.vt_symbol = b.vt_symbol
    where {' and '.join(where)}
    order by b.vt_symbol, b.trade_date
    """
    return pd.read_sql(sql, get_engine(), params=params, parse_dates=["trade_date"])


def _validate_daily_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_DAILY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"daily_bars missing required columns: {', '.join(missing)}")


def _validate_event_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in SUMMARY_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"events missing required columns: {', '.join(missing)}")


def _eligible_main_board_mask(frame: pd.DataFrame) -> pd.Series:
    symbols = frame["vt_symbol"].astype(str).str.upper().str.strip()
    codes = symbols.str.split(".", n=1).str[0]
    sse = symbols.str.endswith(".SSE") & codes.str.startswith(("600", "601", "603", "605"))
    szse = symbols.str.endswith(".SZSE") & codes.str.startswith(("000", "001", "002", "003"))
    names = frame["name"].astype(str).str.upper().str.replace("*", "", regex=False).str.strip()
    excluded_name = names.str.contains("ST|退", regex=True, na=False) | names.str.startswith(("S", "N", "C"))
    return (sse | szse) & ~excluded_name


def _limit_price_series(previous_close: pd.Series) -> pd.Series:
    values = pd.to_numeric(previous_close, errors="coerce")
    return pd.Series(np.floor(values * 110.0 + 0.5 + 1e-9) / 100.0, index=previous_close.index)


def _global_day_maps(trade_dates: pd.Series) -> tuple[dict[pd.Timestamp, pd.Timestamp], dict[pd.Timestamp, pd.Timestamp]]:
    days = sorted(pd.Timestamp(value) for value in trade_dates.dropna().unique())
    previous = {days[index]: days[index - 1] for index in range(1, len(days))}
    following = {days[index]: days[index + 1] for index in range(len(days) - 1)}
    return previous, following


def _forward_return(entry: pd.Series, outcome: pd.Series) -> pd.Series:
    return (outcome / entry - 1.0) * 100.0


def _return_metrics(values: pd.Series) -> dict[str, float | int | None]:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    if returns.empty:
        return {
            "sample_count": 0,
            "win_rate_pct": None,
            "average_return_pct": None,
            "median_return_pct": None,
            "profit_factor": None,
        }
    gains = float(returns[returns > 0].sum())
    losses = abs(float(returns[returns < 0].sum()))
    return {
        "sample_count": int(len(returns)),
        "win_rate_pct": _round((returns > 0).mean() * 100.0),
        "average_return_pct": _round(returns.mean()),
        "median_return_pct": _round(returns.median()),
        "profit_factor": _round(gains / losses) if losses else None,
    }


def _portfolio_summary(events: pd.DataFrame) -> tuple[list[dict[str, object]], dict[str, object]]:
    daily = (
        events.groupby("entry_date", as_index=False)
        .agg(
            outcome_date=("outcome_date", "max"),
            position_count=("vt_symbol", "size"),
            gross_return_pct=("gross_close_return_pct", "mean"),
            net_return_pct=("net_close_return_pct", "mean"),
        )
        .sort_values("entry_date")
    )
    gross_equity = (1.0 + daily["gross_return_pct"] / 100.0).cumprod()
    net_equity = (1.0 + daily["net_return_pct"] / 100.0).cumprod()
    daily["gross_equity"] = gross_equity
    daily["net_equity"] = net_equity
    calendar_days = max((daily["outcome_date"].max() - daily["entry_date"].min()).days, 1)
    gross_ending = float(gross_equity.iloc[-1])
    net_ending = float(net_equity.iloc[-1])
    portfolio = {
        "signal_day_count": len(daily),
        "gross_compound_return_pct": _round((gross_ending - 1.0) * 100.0),
        "net_compound_return_pct": _round((net_ending - 1.0) * 100.0),
        "gross_ending_equity_multiple": _round(gross_ending),
        "net_ending_equity_multiple": _round(net_ending),
        "gross_annualized_return_pct": _annualized_return(gross_ending, calendar_days),
        "net_annualized_return_pct": _annualized_return(net_ending, calendar_days),
        "gross_max_drawdown_pct": _max_drawdown_pct(gross_equity),
        "net_max_drawdown_pct": _max_drawdown_pct(net_equity),
        "gross_profitable_signal_day_rate_pct": _round((daily["gross_return_pct"] > 0).mean() * 100.0),
        "net_profitable_signal_day_rate_pct": _round((daily["net_return_pct"] > 0).mean() * 100.0),
        "average_positions_per_signal_day": _round(daily["position_count"].mean()),
        "max_positions_per_signal_day": int(daily["position_count"].max()),
        "calendar_days": calendar_days,
    }
    daily_results = [
        {
            "entry_date": _date_text(row.entry_date),
            "outcome_date": _date_text(row.outcome_date),
            "position_count": int(row.position_count),
            "gross_return_pct": _round(row.gross_return_pct),
            "net_return_pct": _round(row.net_return_pct),
            "gross_equity": _round(row.gross_equity),
            "net_equity": _round(row.net_equity),
        }
        for row in daily.itertuples(index=False)
    ]
    return daily_results, portfolio


def _annualized_return(ending_equity: float, calendar_days: int) -> float | None:
    if ending_equity <= 0 or calendar_days <= 0:
        return None
    return _round((ending_equity ** (365.0 / calendar_days) - 1.0) * 100.0)


def _max_drawdown_pct(equity: pd.Series) -> float | None:
    if equity.empty:
        return None
    values = pd.concat([pd.Series([1.0]), equity.reset_index(drop=True)], ignore_index=True)
    drawdown = values / values.cummax() - 1.0
    return _round(drawdown.min() * 100.0)


def _sample_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    columns = (
        "entry_date",
        "outcome_date",
        "vt_symbol",
        "name",
        "d1_return_pct",
        "gross_close_return_pct",
        "net_close_return_pct",
        "gross_high_return_pct",
        "gross_low_return_pct",
    )
    return [
        {
            column: _date_text(row.get(column)) if column.endswith("date") else _round_or_value(row.get(column))
            for column in columns
        }
        for row in frame.loc[:, columns].to_dict("records")
    ]


def _empty_event_frame(
    *,
    total_cost_rate: float,
    input_row_count: int = 0,
    eligible_row_count: int = 0,
    available_start: object = None,
    available_end: object = None,
    available_day_count: int = 0,
) -> pd.DataFrame:
    frame = pd.DataFrame(columns=EVENT_COLUMNS)
    frame.attrs.update(
        {
            "total_cost_rate": total_cost_rate,
            "input_row_count": input_row_count,
            "eligible_row_count": eligible_row_count,
            "available_start": available_start,
            "available_end": available_end,
            "available_day_count": available_day_count,
        }
    )
    return frame


def _empty_report(events: pd.DataFrame, *, total_cost_rate: float) -> dict[str, object]:
    empty_metrics = _return_metrics(pd.Series(dtype=float))
    return {
        "status": "insufficient_data",
        "dataset": {
            "input_row_count": int(events.attrs.get("input_row_count", 0)),
            "eligible_row_count": int(events.attrs.get("eligible_row_count", 0)),
            "complete_trading_day_count": int(events.attrs.get("available_day_count", 0)),
            "signal_count": 0,
            "excluded_outcome_count": 0,
            "sample_count": 0,
            "symbol_count": 0,
            "signal_day_count": 0,
            "available_start_date": _date_text(events.attrs.get("available_start")),
            "available_end_date": _date_text(events.attrs.get("available_end")),
            "first_entry_date": None,
            "last_entry_date": None,
            "last_outcome_date": None,
        },
        "costs": _cost_payload(total_cost_rate),
        "trade_summary": {
            "sample_count": 0,
            "gross_win_rate_pct": None,
            "gross_average_return_pct": None,
            "gross_median_return_pct": None,
            "gross_profit_factor": None,
            "net_win_rate_pct": None,
            "net_average_return_pct": None,
            "net_median_return_pct": None,
            "net_profit_factor": None,
            "average_market_return_pct": None,
            "average_excess_return_pct": None,
            "positive_excess_rate_pct": None,
            "d_close_limit_up_rate_pct": None,
        },
        "path_summary": {key: dict(empty_metrics) for key in ("d_open", "d_high", "d_low", "d_close")},
        "portfolio": {
            "signal_day_count": 0,
            "gross_compound_return_pct": 0.0,
            "net_compound_return_pct": 0.0,
            "gross_ending_equity_multiple": 1.0,
            "net_ending_equity_multiple": 1.0,
            "gross_annualized_return_pct": None,
            "net_annualized_return_pct": None,
            "gross_max_drawdown_pct": 0.0,
            "net_max_drawdown_pct": 0.0,
            "gross_profitable_signal_day_rate_pct": None,
            "net_profitable_signal_day_rate_pct": None,
            "average_positions_per_signal_day": None,
            "max_positions_per_signal_day": 0,
            "calendar_days": 0,
        },
        "by_year": [],
        "daily_results": [],
        "samples": {"best": [], "worst": []},
        "limitations": _limitations(),
    }


def _cost_payload(total_cost_rate: float) -> dict[str, float]:
    return {
        "commission_rate_each_side": DEFAULT_COMMISSION_RATE,
        "stamp_tax_rate_sell": DEFAULT_STAMP_TAX_RATE,
        "slippage_bps_each_side": DEFAULT_SLIPPAGE_BPS,
        "total_round_trip_cost_pct": _round(total_cost_rate * 100.0) or 0.0,
    }


def _limitations() -> list[str]:
    return [
        "D-1 收盘买入是日线尾盘成交代理，不证明集合竞价或实盘能够按收盘价完成全部成交。",
        f"只使用每日全市场日线不少于 {MIN_COMPLETE_MARKET_SYMBOLS} 只的完整交易日；更早零散历史不进入统计。",
        "非 ST 过滤使用当前 stocks.name；缺少逐日历史证券简称和风险警示状态，存在幸存者偏差。",
        "涨停价由前收盘价推导；除权除息日若交易所参考价不同，日线无法完全恢复真实涨停价。",
        "同日所有信号等权且没有容量上限、成交额约束或排名，复利是形态研究组合而非可直接执行的资金曲线。",
        "结果属于全样本探索；在成为新策略前仍需做时间外验证、分层稳定性、分钟成交和成本压力测试。",
    ]


def _validate_real_report(events: pd.DataFrame, report: Mapping[str, object]) -> None:
    if events.empty:
        return
    if not events["entry_date"].le(events["outcome_date"]).all():
        raise RuntimeError("event dates are not ordered")
    numeric_columns = (
        "d1_return_pct",
        "gross_open_return_pct",
        "gross_high_return_pct",
        "gross_low_return_pct",
        "gross_close_return_pct",
        "net_close_return_pct",
        "market_return_pct",
        "excess_close_return_pct",
    )
    for column in numeric_columns:
        if not events[column].map(lambda value: isfinite(float(value))).all():
            raise RuntimeError(f"non-finite event value in {column}")
    expected_net = events["gross_close_return_pct"] - DEFAULT_TOTAL_COST_RATE * 100.0
    if not np.allclose(events["net_close_return_pct"], expected_net, atol=1e-9, rtol=0.0):
        raise RuntimeError("net return arithmetic is inconsistent")
    dataset = _mapping(report.get("dataset"))
    valid_count = int(events["outcome_data_valid"].fillna(False).sum())
    if int(dataset.get("sample_count") or 0) != valid_count:
        raise RuntimeError("report sample count is inconsistent")
    if int(dataset.get("signal_count") or 0) != len(events):
        raise RuntimeError("report signal count is inconsistent")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _round(value: object, digits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return round(number, digits)


def _round_or_value(value: object) -> object:
    rounded = _round(value)
    return rounded if rounded is not None else value


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.Timestamp(value)
    return parsed.date().isoformat()


def _pct(value: object) -> str:
    rounded = _round(value)
    return "-" if rounded is None else f"{rounded:.4f}%"


def _number(value: object) -> str:
    rounded = _round(value)
    return "-" if rounded is None else f"{rounded:.4f}"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_date)
    parser.add_argument("--end", type=_parse_date)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.start and args.end and args.start > args.end:
        parser.error("--start must be on or before --end")
    report = run_d2_limit_up_d1_rise_research(start=args.start, end=args.end)
    markdown = render_markdown_report(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(args.output)
        return
    print(markdown, end="")


if __name__ == "__main__":
    main()
