"""Leader first-board research backtest (v2).

每天用 4 个买入时可见因子打分选 TOP3 首板打板买入，按「D+1 开盘高开就拿/低开就走 + 涨停减半
持有」的短线龙头规则回测，输出复利与胜率。研究只读行情源表，仅覆盖写入最新研究结果
和可选证据文件，不触碰正式实时推荐、portfolio 或 ``actionable_recommendations``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig
from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    compute_prior_limit_counts,
    extract_factor_vector,
    extract_first_board_samples,
)
from alphaagent.server.services.limit_up.domain import main_board_limit_price
from alphaagent.server.services.limit_up.morning_window_leader_probability_research import (
    build_calibration,
    filter_morning_window,
    group_by_month,
    score_leader_probability,
)
from alphaagent.server.services.limit_up.repository import load_limit_up_dataset
from alphaagent.server.services.limit_up.leader_first_board_repository import (
    save_leader_backtest_run,
)

STUDY_VERSION = "leader-first-board-backtest-v2"
DEFAULT_MIN_TRAIN_MONTHS = 3
DEFAULT_MIN_EFFECT = 4.0
DEFAULT_MAX_POSITIONS = 3

# 选股因子（expanding 校准）。注：seal_to_turnover_ratio（封单比）已移除——它是
# 未来函数（D 日收盘封单，盘中/早上买入用它选股），保留会让回测虚高。剩余因子中
# 三个来自 D-1，流通市值来自触板事件快照；它们在涨停价入场时均已可见。
CANDIDATE_FACTORS = (
    "float_market_cap",
    "prior_return_5d_pct",
    "prior_3d_up_days",
    "prior_turnover_ratio_5d",
)


def generate_leader_signals(
    factor_samples: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    candidate_factors: Sequence[str],
    min_train_months: int = DEFAULT_MIN_TRAIN_MONTHS,
    min_effect: float = DEFAULT_MIN_EFFECT,
    max_picks: int = DEFAULT_MAX_POSITIONS,
    draws: int = 2000,
    seed: int = 20260730,
) -> list[dict[str, object]]:
    """expanding 月度校准：每月用之前完整月建表，给当月 9:30-11:00 首板打分，按日取 TOP N。

    月度校准只用之前完整月份；同日 TOP N 仍是完整晨盘候选的研究排序，不代表实时到达顺序。
    """

    window = filter_morning_window(factor_samples)
    by_month = group_by_month(window)
    sorted_months = sorted(by_month.keys())

    signals: list[dict[str, object]] = []
    for index, month in enumerate(sorted_months):
        train_months = sorted_months[:index]
        if len(train_months) < min_train_months:
            continue
        train_samples = [
            sample for earlier in train_months for sample in by_month[earlier]
        ]
        calibration = build_calibration(
            train_samples,
            candidate_factors,
            min_effect=min_effect,
            draws=draws,
            seed=seed,
        )
        if not calibration.get("factors"):
            continue
        by_day: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for sample in by_month[month]:
            by_day[str(sample.get("trade_date") or "")].append(sample)
        for day, day_samples in by_day.items():
            scored: list[tuple[float, Mapping[str, object]]] = []
            for sample in day_samples:
                score = score_leader_probability(sample, calibration)
                if score is not None:
                    scored.append((score, sample))
            scored.sort(key=lambda item: item[0], reverse=True)
            for score, sample in scored[:max_picks]:
                signals.append(
                    {
                        "vt_symbol": str(sample.get("vt_symbol") or ""),
                        "trade_date": day,
                        "score": score,
                        "name": sample.get("name"),
                        "first_limit_time": sample.get("first_limit_time"),
                    }
                )
    return signals


# ── Task 2: backtest engine (auction branch + limit-half holding) ──────


@dataclass
class _Position:
    vt_symbol: str
    volume: int
    entry_date: str
    buy_price: float
    name: str = ""
    first_limit_time: str = ""
    cash_cost: float = 0.0
    buy_fee: float = 0.0
    initial_volume: int = 0  # 买入总量（不变，供 limit_half 部分卖出按比例分摊成本）


def simulate_leader_first_board_account(
    signals: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[str],
    *,
    config: CashBacktestConfig | None = None,
) -> dict[str, object]:
    """每天买入 TOP3 首板，按「高开就拿/低开就走 + 涨停减半」规则持仓回测。"""

    if config is None:
        config = CashBacktestConfig(max_positions=DEFAULT_MAX_POSITIONS)
    bar_index = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")): bar
        for bar in bars
    }
    signals_by_date: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for signal in signals:
        signals_by_date[str(signal.get("trade_date") or "")].append(signal)
    for day in signals_by_date:
        signals_by_date[day].sort(
            key=lambda value: float(value.get("score") or 0.0), reverse=True
        )

    cash = config.initial_cash
    positions: dict[str, _Position] = {}
    closed_trades: list[dict[str, object]] = []
    equity_curve: list[dict[str, object]] = []
    peak_equity = config.initial_cash
    prev_map = {
        trade_dates[i]: (trade_dates[i - 1] if i > 0 else None)
        for i in range(len(trade_dates))
    }

    def position_value(symbol: str, today: str) -> float:
        bar = bar_index.get((symbol, today))
        return float(bar.get("close_price") or 0.0) if bar else 0.0

    def sell(
        symbol: str,
        pos: _Position,
        exit_date: str,
        exit_price: float,
        volume: int,
        reason: str,
    ) -> None:
        nonlocal cash
        execution = cash_ledger.calculate_sell_execution(
            raw_price=exit_price,
            volume=volume,
            cost_price=pos.buy_price,
            commission_rate=config.commission_rate,
            stamp_tax_rate=config.stamp_tax_rate,
            slippage_bps=config.slippage_bps,
            minimum_commission=config.minimum_commission,
            transfer_fee_rate=config.transfer_fee_rate,
        )
        cash += execution.cash_delta
        # 双边净口径：净盈亏 = 这批卖出回笼 − 这批对应的买入成本。limit_half 是部分卖出，
        # 必须按 sell_volume/initial_volume 比例分摊 cash_cost，否则把整个仓位成本算到半仓
        # 回笼上会得到荒谬的大亏（如 -45%）。全部卖出时比例=1，与 cash_backtest 一致。
        total_vol = pos.initial_volume or pos.volume
        allocation = volume / total_vol if total_vol else 1.0
        sell_cost = pos.cash_cost * allocation
        buy_fee = pos.buy_fee * allocation
        net_pnl = execution.cash_delta - sell_cost
        return_pct = round(net_pnl / sell_cost * 100, 4) if sell_cost else None
        closed_trades.append(
            {
                "vt_symbol": symbol,
                "name": pos.name or symbol,
                "entry_date": pos.entry_date,
                "exit_date": exit_date,
                "buy_price": pos.buy_price,
                "buy_amount": pos.buy_price * volume,
                "buy_fee": buy_fee,
                "cash_cost": sell_cost,
                "exit_price": execution.price,
                "volume": volume,
                "sell_amount": execution.amount,
                "fee": execution.fee,
                "sell_fee": execution.fee,
                "total_fee": buy_fee + execution.fee,
                "net_pnl": net_pnl,
                "return_pct": return_pct,
                "is_win": net_pnl > 0,
                "exit_reason": reason,
                "first_limit_time": pos.first_limit_time,
            }
        )

    for today in trade_dates:
        prev_day = prev_map[today]
        # 1. 处理已有持仓（前日及更早买入的）
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            bar = bar_index.get((symbol, today))
            prev_bar = bar_index.get((symbol, prev_day)) if prev_day else None
            if not bar or not prev_bar:
                continue
            prev_close = float(prev_bar.get("close_price") or 0.0)
            if prev_close <= 0:
                continue
            open_price = float(bar.get("open_price") or 0.0)
            close_price = float(bar.get("close_price") or 0.0)
            limit_price = main_board_limit_price(prev_close)
            if open_price <= prev_close:
                sell(symbol, pos, today, open_price, pos.volume, "open_below_prev_close")
                del positions[symbol]
            elif close_price >= limit_price - max(0.02, limit_price * 0.001):
                sell_vol = (pos.volume // 2 // config.lot_size) * config.lot_size
                if sell_vol > 0:
                    sell(symbol, pos, today, close_price, sell_vol, "limit_half")
                    pos.volume -= sell_vol
                if pos.volume <= 0:
                    del positions[symbol]
            else:
                # 不涨停 → 走人（收盘卖）
                sell(symbol, pos, today, close_price, pos.volume, "close_not_limit")
                del positions[symbol]
        # 2. 买入当日 TOP N 新信号
        for signal in signals_by_date.get(today, []):
            if len(positions) >= config.max_positions:
                break
            symbol = str(signal.get("vt_symbol") or "")
            if symbol in positions:
                continue
            bar = bar_index.get((symbol, today))
            prev_bar = bar_index.get((symbol, prev_day)) if prev_day else None
            if not bar or not prev_bar:
                continue
            prev_close = float(prev_bar.get("close_price") or 0.0)
            if prev_close <= 0:
                continue
            limit_price = main_board_limit_price(prev_close)
            total_equity_now = cash + sum(
                p.volume * position_value(s, today) for s, p in positions.items()
            )
            target_cash = total_equity_now / config.max_positions
            buy = cash_ledger.calculate_buy_execution(
                raw_price=limit_price,
                cash=cash,
                target_cash=target_cash,
                commission_rate=config.commission_rate,
                slippage_bps=config.slippage_bps,
                lot_size=config.lot_size,
                minimum_commission=config.minimum_commission,
                transfer_fee_rate=config.transfer_fee_rate,
                max_price=limit_price,
            )
            if buy.volume <= 0:
                continue
            cash = buy.cash_after
            positions[symbol] = _Position(
                symbol,
                buy.volume,
                today,
                buy.price,
                name=str(signal.get("name") or symbol),
                first_limit_time=str(signal.get("first_limit_time") or ""),
                cash_cost=buy.amount + buy.fee,
                buy_fee=buy.fee,
                initial_volume=buy.volume,
            )
        # 3. mark + equity
        market_value = sum(
            p.volume * position_value(s, today) for s, p in positions.items()
        )
        total_equity = cash + market_value
        peak_equity = max(peak_equity, total_equity)
        drawdown = (total_equity / peak_equity - 1) if peak_equity > 0 else 0.0
        equity_curve.append(
            {
                "trade_date": today,
                "cash": round(cash, 4),
                "market_value": round(market_value, 4),
                "total_equity": round(total_equity, 4),
                "drawdown_pct": round(drawdown * 100, 4),
            }
        )

    # 4. 回测结束，剩余持仓按末日收盘清仓
    last_day = trade_dates[-1] if trade_dates else ""
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        bar = bar_index.get((symbol, last_day))
        exit_price = float(bar.get("close_price") or pos.buy_price) if bar else pos.buy_price
        sell(symbol, pos, last_day, exit_price, pos.volume, "final_close")
        del positions[symbol]

    return {
        "execution_valid": False,
        "account_config": {
            "initial_cash": config.initial_cash,
            "max_positions": config.max_positions,
            "commission_rate": config.commission_rate,
            "stamp_tax_rate": config.stamp_tax_rate,
            "slippage_bps": config.slippage_bps,
        },
        "execution_summary": _build_summary(config, cash, closed_trades, equity_curve),
        "equity_curve": equity_curve,
        "closed_trades": closed_trades,
    }


def _build_summary(config, final_cash, closed_trades, equity_curve):
    positions: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for trade in closed_trades:
        positions[
            (str(trade.get("vt_symbol") or ""), str(trade.get("entry_date") or ""))
        ].append(trade)
    outcomes = []
    for parts in positions.values():
        cash_cost = sum(float(part.get("cash_cost") or 0.0) for part in parts)
        net_pnl = sum(float(part.get("net_pnl") or 0.0) for part in parts)
        outcomes.append(
            {
                "net_pnl": net_pnl,
                "return_pct": net_pnl / cash_cost * 100 if cash_cost else None,
                "is_win": net_pnl > 0,
            }
        )
    wins = [outcome for outcome in outcomes if outcome["is_win"]]
    losses = [outcome for outcome in outcomes if not outcome["is_win"]]
    gross_profit = sum(t.get("net_pnl", 0.0) for t in wins)
    gross_loss = sum(abs(t.get("net_pnl", 0.0)) for t in losses)
    returns = [
        outcome["return_pct"]
        for outcome in outcomes
        if outcome["return_pct"] is not None
    ]
    max_drawdown = min(
        (row.get("drawdown_pct", 0.0) for row in equity_curve), default=0.0
    )
    return {
        "initial_cash": config.initial_cash,
        "final_equity": round(final_cash, 4),
        "trade_count": len(outcomes),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(outcomes) * 100, 4)
        if outcomes
        else None,
        "total_return_pct": round((final_cash / config.initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "total_fees": round(
            sum(float(trade.get("total_fee") or 0.0) for trade in closed_trades), 4
        ),
    }


# ── Task 3: orchestration, markdown, CLI ───────────────────────────────

_RESEARCH_NOTES = (
    "每天用 3 个 D-1 因子和触板时流通市值 expanding 校准打分选 TOP3 首板，涨停价打板买入。",
    "D+1 起每日开盘：高开（>前日收盘）就拿、低开/平盘就走；拿着当天涨停则减半留、不涨停收盘走。",
    "expanding 校准只用过去完整月份；每日 TOP3 是完整晨盘候选的研究排序。",
    "买入假设涨停价成交（实盘封单厚可能买不到），回测偏乐观；D+1 用开盘价代理竞价。",
    "13 个月单市场段，复利结果不可外推；execution_valid 恒 False，仅研究证据。",
)


def build_backtest_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    min_consecutive_boards: int = 3,
    min_train_months: int = DEFAULT_MIN_TRAIN_MONTHS,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    min_effect: float = DEFAULT_MIN_EFFECT,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, object]:
    """编排：首板+因子 → expanding 信号 → 回测引擎 → 报告。纯函数，不连 DB。"""

    samples = extract_first_board_samples(
        events, calendar, min_consecutive_boards=min_consecutive_boards
    )
    prior_limits = compute_prior_limit_counts(samples, events, calendar)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)

    factor_samples: list[dict[str, object]] = []
    for sample in samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        symbol_bars = bars_by_symbol.get(symbol, [])
        d_bar = next(
            (bar for bar in symbol_bars if str(bar.get("trade_date") or "") == trade_date),
            None,
        )
        factors = extract_factor_vector(
            sample,
            symbol_bars=symbol_bars,
            d_bar=d_bar,
            prior_limits=prior_limits.get((symbol, trade_date), {}),
        )
        factors["vt_symbol"] = symbol
        factors["name"] = sample.get("name")
        factors["trade_date"] = trade_date
        factors["first_limit_time"] = sample.get("first_limit_time")
        factor_samples.append(factors)

    signals = generate_leader_signals(
        factor_samples,
        calendar,
        candidate_factors=CANDIDATE_FACTORS,
        min_train_months=min_train_months,
        min_effect=min_effect,
        max_picks=max_positions,
        draws=draws,
        seed=seed,
    )
    config = CashBacktestConfig(max_positions=max_positions)
    result = simulate_leader_first_board_account(signals, daily_bars, calendar, config=config)
    result["study_version"] = STUDY_VERSION
    result["signal_count"] = len(signals)
    result["first_board_count"] = len(samples)
    result["min_consecutive_boards"] = min_consecutive_boards
    result["min_train_months"] = min_train_months
    result["notes"] = list(_RESEARCH_NOTES)
    return result


def run_backtest(
    *,
    start: date,
    end: date,
    min_consecutive_boards: int = 3,
    min_train_months: int = DEFAULT_MIN_TRAIN_MONTHS,
    max_positions: int = DEFAULT_MAX_POSITIONS,
) -> dict[str, object]:
    """Load frozen dataset and run the leader first-board backtest."""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    daily_bars = dataset["daily_bars"]
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    report = build_backtest_report(
        events,
        daily_bars,
        calendar,
        min_consecutive_boards=min_consecutive_boards,
        min_train_months=min_train_months,
        max_positions=max_positions,
    )
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["input_fingerprint"] = _input_fingerprint(events, daily_bars, report["signal_count"])
    return report


def _input_fingerprint(events, daily_bars, signal_count) -> str:
    payload = f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{signal_count}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render_markdown(result: Mapping[str, object]) -> str:
    summary = _mapping(result.get("execution_summary"))
    config = _mapping(result.get("account_config"))
    trades = result.get("closed_trades") or []
    reason_counts = Counter(str(t.get("exit_reason")) for t in trades)
    lines = [
        "# Leader First-Board Backtest",
        "",
        "## Boundary",
        "",
        f"- 状态：研究版本 `{str(result.get('study_version') or '-')}`；``execution_valid`` 恒为 False。",
        "- 本报告只读 `stock_events`/`stock_daily_bars`，不修改 `limit-up-core-abc-v2`、C、实时推荐或账户。",
        "- 每天用 3 个 D-1 因子和触板时流通市值 expanding 校准选 TOP3 首板，涨停价打板买入。",
        "- 每日 TOP3 使用完整晨盘候选横截面，属于研究代理，不等同于实时到达顺序。",
        "- D+1 起：开盘高开就拿、低开/平盘走；涨停减半留、不涨停收盘走。",
        f"- 连板阈值 `>= {_integer(result.get('min_consecutive_boards'))}`；"
        f"max_positions `{_integer(config.get('max_positions'))}`；"
        f"train 前 {_integer(result.get('min_train_months'))} 月。",
        "",
        "## Coverage",
        "",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
        f"- 首板样本：{_integer(result.get('first_board_count'))}；信号数：{_integer(result.get('signal_count'))}；"
        f"成交笔数：{_integer(summary.get('trade_count'))}。",
        f"- 输入指纹：`{str(result.get('input_fingerprint') or '-')}`。",
        "",
        "## Summary",
        "",
        f"- 初始资金：`{_fmt(summary.get('initial_cash'))}`；最终权益：`{_fmt(summary.get('final_equity'))}`。",
        f"- **总收益（复利）**：`{_fmt(summary.get('total_return_pct'))}%`；"
        f"**胜率**：`{_fmt(summary.get('win_rate'))}%`（{_integer(summary.get('win_count'))}/{_integer(summary.get('trade_count'))}）。",
        f"- 最大回撤：`{_fmt(summary.get('max_drawdown_pct'))}%`；利润因子：`{_fmt(summary.get('profit_factor'))}`；"
        f"平均收益：`{_fmt(summary.get('average_return_pct'))}%`；总费用：`{_fmt(summary.get('total_fees'))}`。",
        "",
        "## Exit Reason Distribution",
        "",
    ]
    if reason_counts:
        for reason, count in reason_counts.most_common():
            lines.append(f"- `{reason}`：{count} 笔")
    else:
        lines.append("- （无成交）")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- 本报告为只读回测证据，不产出可执行信号，不改变正式门或实时推荐。",
            "- 回测假设涨停价成交（偏乐观）、D+1 用开盘价代理竞价；实盘须扣减成交不确定性。",
            "- 13 个月单市场段，复利结果不可外推为普适规律。",
            "",
            "## Evidence Boundary",
            "",
            "- JSON 含 equity_curve 与全部 closed_trades 明细；Markdown 只显示汇总，避免事后最高被误读为可交易规则。",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the leader first-board research and persist its latest result."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--min-consecutive-boards", type=int, default=3)
    parser.add_argument("--max-positions", type=int, default=DEFAULT_MAX_POSITIONS)
    parser.add_argument("--json-output", type=Path, required=False)
    parser.add_argument("--markdown-output", type=Path, required=False)
    arguments = parser.parse_args(argv)

    result = run_backtest(
        start=arguments.start,
        end=arguments.end,
        min_consecutive_boards=arguments.min_consecutive_boards,
        max_positions=arguments.max_positions,
    )
    # 写库（API 数据源，单行 id=1 覆盖）
    save_leader_backtest_run(STUDY_VERSION, result)
    if arguments.json_output:
        arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    if arguments.markdown_output:
        arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _fmt(value: object) -> str:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return "-"
    return f"{number:.4f}" if number is not None else "-"


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
