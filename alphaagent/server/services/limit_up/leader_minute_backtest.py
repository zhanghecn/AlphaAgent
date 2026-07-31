"""Leader minute-level precise backtest.

用 stock_minute_bars 做分钟级精准回测，买入点 = 开盘 10 分钟窗口（9:31-9:40）内
1 分钟涨幅 ≥ surge_pct 或 距开盘累计 ≥ cum_pct 的那根 bar 的 close（真实可执行价，
替代 leader_first_board_backtest 的涨停价打板上界）。复用 5 因子 expanding TOP3 选股；
D+1 卖出沿用日线规则（高开拿/低开走/涨停减半），双边净口径 + 比例分摊。

研究只读 PostgreSQL，只写 ``leader_minute_backtest_runs`` 表，绝不触碰实时表/portfolio。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
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
from alphaagent.server.services.limit_up.leader_first_board_backtest import (
    CANDIDATE_FACTORS,
    DEFAULT_MAX_POSITIONS,
    DEFAULT_MIN_EFFECT,
    DEFAULT_MIN_TRAIN_MONTHS,
    generate_leader_signals,
)
from alphaagent.server.services.limit_up.repository import (
    load_limit_up_dataset,
    load_minute_bars,
)
from alphaagent.server.services.limit_up.leader_minute_repository import (
    save_minute_backtest_run,
)

STUDY_VERSION = "leader-minute-backtest-v1"
WINDOW_START = "09:31:00"
WINDOW_END = "09:40:00"
DEFAULT_SURGE_PCT = 2.0  # 1 分钟涨幅阈值（%）
DEFAULT_CUM_PCT = 7.0  # 距开盘价累计涨幅阈值（%）


@dataclass
class _Position:
    vt_symbol: str
    volume: int
    entry_date: str
    buy_price: float
    name: str = ""
    buy_time: str = ""  # 分钟级 bar_time（HH:MM:SS）
    first_limit_time: str = ""
    cash_cost: float = 0.0
    initial_volume: int = 0


def simulate_minute_account(
    signals: Sequence[Mapping[str, object]],
    minute_bars: Mapping[tuple[str, str], Sequence[Mapping[str, object]]],
    daily_bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[str],
    *,
    config: CashBacktestConfig | None = None,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
) -> dict[str, object]:
    """分钟级买入（窗口内 surge/cum 触发 bar close）+ D+1 日线卖出。"""

    if config is None:
        config = CashBacktestConfig(max_positions=DEFAULT_MAX_POSITIONS)
    daily_index = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")): bar
        for bar in daily_bars
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

    def daily_close(symbol: str, today: str) -> float:
        bar = daily_index.get((symbol, today))
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
        total_vol = pos.initial_volume or pos.volume
        sell_cost = pos.cash_cost * (volume / total_vol) if total_vol else pos.cash_cost
        net_pnl = execution.cash_delta - sell_cost
        return_pct = round(net_pnl / sell_cost * 100, 4) if sell_cost else None
        closed_trades.append(
            {
                "vt_symbol": symbol,
                "name": pos.name or symbol,
                "entry_date": pos.entry_date,
                "exit_date": exit_date,
                "buy_price": pos.buy_price,
                "buy_time": pos.buy_time,
                "first_limit_time": pos.first_limit_time,
                "exit_price": execution.price,
                "volume": volume,
                "sell_amount": execution.amount,
                "fee": execution.fee,
                "net_pnl": net_pnl,
                "return_pct": return_pct,
                "is_win": net_pnl > 0,
                "exit_reason": reason,
            }
        )

    for today in trade_dates:
        prev_day = prev_map[today]
        # 1. D+1 卖出（持仓，日线规则，同 leader_first_board_backtest）
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            bar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
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
                sell(symbol, pos, today, close_price, pos.volume, "close_not_limit")
                del positions[symbol]
        # 2. D 日分钟级买入
        for signal in signals_by_date.get(today, []):
            if len(positions) >= config.max_positions:
                break
            symbol = str(signal.get("vt_symbol") or "")
            if symbol in positions:
                continue
            today_bar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
            if not today_bar or not prev_bar:
                continue
            prev_close = float(prev_bar.get("close_price") or 0.0)
            open_price = float(today_bar.get("open_price") or 0.0)
            if prev_close <= 0 or open_price <= 0:
                continue
            first_limit_time = str(signal.get("first_limit_time") or "")
            bars = minute_bars.get((symbol, today)) or []
            prev_window_close: float | None = None
            buy_bar: Mapping[str, object] | None = None
            buy_time_text = ""
            for bar in bars:
                bt_full = str(bar.get("bar_time") or "")
                bt_time = bt_full[11:19] if len(bt_full) >= 19 else bt_full[-8:]
                if bt_time < window_start or bt_time > window_end:
                    continue
                close = float(bar.get("close_price") or 0.0)
                if close <= 0:
                    continue
                surge = (
                    (close / prev_window_close - 1) * 100
                    if prev_window_close
                    else 0.0
                )
                cum = (close / open_price - 1) * 100
                if (prev_window_close and surge >= surge_pct) or cum >= cum_pct:
                    buy_bar = bar
                    buy_time_text = bt_time
                    break
                prev_window_close = close
            if buy_bar is None:
                continue  # 窗口内无 surge/cum 触发（含秒板已封死）→ 跳过
            if not first_limit_time or first_limit_time <= buy_time_text:
                continue  # 触板在买入前/同时（已封板买不到）→ 跳过
            buy_price = float(buy_bar.get("close_price") or 0.0)
            if buy_price <= 0:
                continue
            total_equity_now = cash + sum(
                p.volume * daily_close(s, today) for s, p in positions.items()
            )
            target_cash = total_equity_now / config.max_positions
            buy = cash_ledger.calculate_buy_execution(
                raw_price=buy_price,
                cash=cash,
                target_cash=target_cash,
                commission_rate=config.commission_rate,
                slippage_bps=config.slippage_bps,
                lot_size=config.lot_size,
                minimum_commission=config.minimum_commission,
                transfer_fee_rate=config.transfer_fee_rate,
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
                buy_time=buy_time_text,
                first_limit_time=first_limit_time,
                cash_cost=buy.amount + buy.fee,
                initial_volume=buy.volume,
            )
        # 3. mark + equity
        market_value = sum(
            p.volume * daily_close(s, today) for s, p in positions.items()
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
        bar = daily_index.get((symbol, last_day))
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
    wins = [t for t in closed_trades if t.get("is_win")]
    losses = [t for t in closed_trades if not t.get("is_win")]
    gross_profit = sum(t.get("net_pnl", 0.0) for t in wins)
    gross_loss = sum(abs(t.get("net_pnl", 0.0)) for t in losses)
    returns = [
        t.get("return_pct") for t in closed_trades if t.get("return_pct") is not None
    ]
    max_drawdown = min(
        (row.get("drawdown_pct", 0.0) for row in equity_curve), default=0.0
    )
    return {
        "initial_cash": config.initial_cash,
        "final_equity": round(final_cash, 4),
        "trade_count": len(closed_trades),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(closed_trades) * 100, 4)
        if closed_trades
        else None,
        "total_return_pct": round((final_cash / config.initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "total_fees": round(sum(t.get("fee", 0.0) for t in closed_trades), 4),
    }


def build_minute_backtest_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    min_consecutive_boards: int = 3,
    min_train_months: int = DEFAULT_MIN_TRAIN_MONTHS,
    max_positions: int = DEFAULT_MAX_POSITIONS,
    min_effect: float = DEFAULT_MIN_EFFECT,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, object]:
    """编排：首板+因子 → expanding 信号 → 加载分钟 bar → 分钟级回测。"""

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
    # 只加载信号涉及的票-日分钟 bar（避免全量扫描）
    pairs = [
        (str(signal.get("vt_symbol") or ""), date.fromisoformat(str(signal.get("trade_date"))))
        for signal in signals
        if signal.get("vt_symbol") and signal.get("trade_date")
    ]
    minute_bars = load_minute_bars(pairs)
    covered_signals = sum(
        1
        for signal in signals
        if minute_bars.get((str(signal.get("vt_symbol") or ""), str(signal.get("trade_date") or "")))
    )
    config = CashBacktestConfig(max_positions=max_positions)
    result = simulate_minute_account(
        signals,
        minute_bars,
        daily_bars,
        calendar,
        config=config,
        surge_pct=surge_pct,
        cum_pct=cum_pct,
        window_start=window_start,
        window_end=window_end,
    )
    result["study_version"] = STUDY_VERSION
    result["signal_count"] = len(signals)
    result["minute_covered_signals"] = covered_signals
    result["surge_pct"] = surge_pct
    result["cum_pct"] = cum_pct
    result["window"] = f"{window_start}-{window_end}"
    result["notes"] = [
        "分钟级精准回测：买入点 = 开盘10分钟窗口内 surge≥阈值 或 累计涨幅≥阈值的 bar close。",
        "D+1 卖出沿用日线规则（高开拿/低开走/涨停减半），双边净口径 + 比例分摊。",
        "秒板（触板在买入前/窗口内已封死）自动跳过——实盘买不到。",
        f"仅覆盖有分钟数据的信号 {covered_signals}/{len(signals)}（stock_minute_bars ~33% 覆盖），有选择偏差。",
        "对照 leader_first_board 涨停价打板的上界看真实可执行收益差距。",
    ]
    return result


def run_minute_backtest(
    *,
    start: date,
    end: date,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
) -> dict[str, object]:
    """Load dataset + minute bars, run the leader minute-level backtest."""

    dataset = load_limit_up_dataset(start, end)
    daily_bars = dataset["daily_bars"]
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    report = build_minute_backtest_report(
        dataset["events"],
        daily_bars,
        calendar,
        surge_pct=surge_pct,
        cum_pct=cum_pct,
    )
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    return report


def main(argv: Sequence[str] | None = None) -> None:
    """Run the leader minute-level backtest and write to DB."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--surge-pct", type=float, default=DEFAULT_SURGE_PCT)
    parser.add_argument("--cum-pct", type=float, default=DEFAULT_CUM_PCT)
    parser.add_argument("--json-output", type=Path, required=False)
    arguments = parser.parse_args(argv)

    result = run_minute_backtest(
        start=arguments.start,
        end=arguments.end,
        surge_pct=arguments.surge_pct,
        cum_pct=arguments.cum_pct,
    )
    save_minute_backtest_run(STUDY_VERSION, result)
    if arguments.json_output:
        arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
