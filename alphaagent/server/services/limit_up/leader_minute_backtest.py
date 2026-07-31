"""Leader minute-level backtest v2（全市场 + 无未来函数）。

修复 v1 的样本选择偏差：v1 从涨停池 is_sealed 事件出发——先取事后确认涨停的首板，
再在其中找触板前的分钟买点，胜率被样本「必然涨停」虚高，不能称为全市场真实可执行回测。

v2 的 universe = 当日有分钟数据的全市场主板非 ST 股票，决策只用 D-1 及更早数据 +
盘中可观测数据：

- 触发：9:31-9:40 窗口内 1 分钟 surge ≥ 阈值或距开盘 cum ≥ 阈值，按触发 bar close 买入。
- 封板跳过：触发 bar close ≥ 涨停价（昨收 ×1.10）→ 当时已封板买不到（价格可观测，
  不使用 events 的 first_limit_time）。
- 一字板跳过：开盘价 ≥ 涨停价。
- 覆盖过滤：仅在当日分钟数据覆盖 ≥ MIN_DAY_COVERAGE 只的日子交易（覆盖数盘中可
  观测；稀疏日多为涨停事件票回填，存在覆盖偏差，整日跳过）。
- 因子：4 个 D-1 因子（流通市值/前5日涨幅/前3日上涨天数/前5日量比），触发群体月度
  expanding 校准，标签 = D+1 净赢（训练只用之前完整月份）。
- 卖出：D+1 日线规则（低开走/涨停减半/收盘走），双边费用 + 比例分摊。

研究只读 PostgreSQL，只写 ``leader_minute_backtest_runs`` 表。
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig
from alphaagent.server.services.limit_up.domain import main_board_limit_price
from alphaagent.server.services.limit_up.morning_window_leader_probability_research import (
    build_calibration,
    score_leader_probability,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_stock_names,
    load_window_minute_bars,
)
from alphaagent.server.services.limit_up.leader_minute_repository import (
    save_minute_backtest_run,
)

STUDY_VERSION = "leader-minute-backtest-v2"
WINDOW_START = "09:31:00"
WINDOW_END = "09:40:00"
DEFAULT_SURGE_PCT = 2.0  # 1 分钟涨幅阈值（%）
DEFAULT_CUM_PCT = 7.0  # 距开盘价累计涨幅阈值（%）
DEFAULT_MAX_POSITIONS = 3
DEFAULT_MIN_EFFECT = 4.0
MIN_DAY_COVERAGE = 600  # 宽覆盖日下限：当日有分钟数据的票数（盘中可观测）
MIN_TRAIN_SAMPLES = 20  # 月度 expanding 校准的最少已标答触发样本数
MAIN_BOARD_PREFIXES = ("60", "00")
PAPER_NOTIONAL = 100_000.0  # 训练标签用的单位名义本金（不进真实账户）

# 选股因子（全部 D-1 可观测，无任何当日/事后数据）
CANDIDATE_FACTORS = (
    "float_market_cap",
    "prior_return_5d_pct",
    "prior_3d_up_days",
    "prior_turnover_ratio_5d",
)


def _float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _is_main_board(vt_symbol: str) -> bool:
    return vt_symbol.split(".")[0].startswith(MAIN_BOARD_PREFIXES)


def _d1_factors(bars_before: Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    """由 D 日之前的日线（升序，需含 D-1..D-6）计算 4 个 D-1 因子，不足则 None。"""

    if len(bars_before) < 6:
        return None
    d1 = bars_before[-1]
    prev_close = _float(d1.get("close_price"))
    base_close = _float(bars_before[-6].get("close_price"))
    if not prev_close or not base_close:
        return None
    # 前3日上涨天数：D-3..D-1 各自 close > 其前一日 close
    up_days = 0
    for index in (-3, -2, -1):
        current = _float(bars_before[index].get("close_price")) or 0.0
        previous = _float(bars_before[index - 1].get("close_price")) or 0.0
        if current and previous and current > previous:
            up_days += 1
    # 前5日量比 = D-1 成交额 / 前5日（D-2..D-6）日均成交额（与打板版同口径）
    history_amounts = [_float(row.get("turnover")) for row in bars_before[-6:-1]]
    usable = [value for value in history_amounts if value and value > 0]
    d1_amount = _float(d1.get("turnover"))
    turnover_ratio = (
        d1_amount / (sum(usable) / len(usable))
        if usable and d1_amount and d1_amount > 0
        else None
    )
    # 流通市值 = D-1 成交额 / (D-1 换手率/100)（历史推导值，不用当前快照）
    turnover_rate = _float(d1.get("turnover_rate"))
    float_market_cap = (
        d1_amount / (turnover_rate / 100)
        if d1_amount and turnover_rate and turnover_rate > 0
        else None
    )
    return {
        "prior_return_5d_pct": round((prev_close / base_close - 1) * 100, 4),
        "prior_3d_up_days": up_days,
        "prior_turnover_ratio_5d": round(turnover_ratio, 4) if turnover_ratio else None,
        "float_market_cap": round(float_market_cap, 2) if float_market_cap else None,
    }


def _d1_exit(bar: Mapping[str, object], prev_close: float) -> tuple[str, float]:
    """D+1 卖出决策（同打板口径）：返回 (exit_kind, price)。"""

    open_price = _float(bar.get("open_price")) or 0.0
    close_price = _float(bar.get("close_price")) or 0.0
    limit_price = main_board_limit_price(prev_close)
    if open_price <= prev_close:
        return "open_below_prev_close", open_price
    if close_price >= limit_price - max(0.02, limit_price * 0.001):
        return "limit_close", close_price
    return "close_not_limit", close_price


def _board_status(day_bar: Mapping[str, object], prev_close: float) -> str:
    """当日封板结局（结果信息，仅供交割单展示，不参与任何决策）。"""

    close_price = _float(day_bar.get("close_price")) or 0.0
    high_price = _float(day_bar.get("high_price")) or 0.0
    limit_price = main_board_limit_price(prev_close)
    tolerance = max(0.02, limit_price * 0.001)
    if close_price >= limit_price - tolerance:
        return "sealed"
    if high_price >= limit_price - tolerance:
        return "failed"
    return "no_limit"


def _trigger_buy(
    window_bars: Sequence[Mapping[str, object]],
    *,
    open_price: float,
    prev_close: float,
    surge_pct: float,
    cum_pct: float,
    window_start: str,
    window_end: str,
) -> dict[str, object] | None:
    """窗口内 surge/cum 触发 → 触发 bar close 买入；只用触发时点及之前的数据。"""

    if open_price <= 0 or prev_close <= 0:
        return None
    limit_price = main_board_limit_price(prev_close)
    if open_price >= limit_price:
        return None  # 一字板开盘即封，买不到
    prev_window_close: float | None = None
    for bar in window_bars:
        bar_time = str(bar.get("bar_time") or "")
        if bar_time < window_start or bar_time > window_end:
            continue
        close = _float(bar.get("close_price")) or 0.0
        if close <= 0:
            continue
        surge = (close / prev_window_close - 1) * 100 if prev_window_close else 0.0
        cum = (close / open_price - 1) * 100
        if (prev_window_close and surge >= surge_pct) or cum >= cum_pct:
            if close >= limit_price:
                return None  # 触发瞬间已封板（价格可观测），买不到
            return {"buy_price": close, "buy_time": bar_time, "cum_pct": round(cum, 4)}
        prev_window_close = close
    return None


def _build_month_calibration(
    train_samples: Sequence[Mapping[str, object]],
    month: str,
    *,
    min_train_samples: int,
    min_effect: float,
) -> dict[str, object] | None:
    """expanding 校准：只用严格早于 month 且标签已知的触发样本。"""

    train = [
        sample
        for sample in train_samples
        if str(sample.get("month") or "") < month and sample.get("is_leader") is not None
    ]
    if len(train) < min_train_samples:
        return None
    calibration = build_calibration(train, CANDIDATE_FACTORS, min_effect=min_effect)
    return calibration if calibration.get("factors") else None


@dataclass
class _Position:
    vt_symbol: str
    volume: int
    entry_date: str
    buy_price: float
    name: str = ""
    buy_time: str = ""
    cash_cost: float = 0.0
    initial_volume: int = 0
    board_status: str = "no_limit"


@dataclass
class _PaperPosition:
    """训练标签用的单位持仓（不进真实账户，不占用仓位）。"""

    sample: dict[str, object]
    volume: int
    buy_price: float
    cash_cost: float
    initial_volume: int
    net_pnl: float = 0.0


def simulate_allmarket_minute(
    *,
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, object]]],
    daily_index: Mapping[tuple[str, str], Mapping[str, object]],
    calendar: Sequence[str],
    names: Mapping[str, str],
    minute_loader: Callable[[date], Mapping[str, Sequence[Mapping[str, object]]]],
    config: CashBacktestConfig | None = None,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    min_day_coverage: int = MIN_DAY_COVERAGE,
    min_train_samples: int = MIN_TRAIN_SAMPLES,
    min_effect: float = DEFAULT_MIN_EFFECT,
) -> dict[str, object]:
    """全市场分钟级回测：触发扫描 → D-1 因子校准排序 → TOP N 买入 → D+1 卖出。"""

    if config is None:
        config = CashBacktestConfig(max_positions=DEFAULT_MAX_POSITIONS)
    cash = config.initial_cash
    positions: dict[str, _Position] = {}
    paper_positions: dict[str, _PaperPosition] = {}
    train_samples: list[dict[str, object]] = []
    closed_trades: list[dict[str, object]] = []
    equity_curve: list[dict[str, object]] = []
    calibrations: dict[str, object | None] = {}
    peak_equity = config.initial_cash
    prev_map = {
        calendar[i]: (calendar[i - 1] if i > 0 else None) for i in range(len(calendar))
    }
    symbol_dates: dict[str, list[str]] = {
        symbol: [str(bar.get("trade_date") or "") for bar in rows]
        for symbol, rows in bars_by_symbol.items()
    }
    stats = {
        "days_total": 0,
        "days_tradeable": 0,
        "days_skipped_low_coverage": 0,
        "coverage_total": 0,
        "trigger_count": 0,
        "calibration_months": 0,
    }

    def daily_close(symbol: str, today: str) -> float:
        bar = daily_index.get((symbol, today))
        return _float(bar.get("close_price")) or 0.0 if bar else 0.0

    def sell_execution(price: float, volume: int, cost_price: float):
        return cash_ledger.calculate_sell_execution(
            raw_price=price,
            volume=volume,
            cost_price=cost_price,
            commission_rate=config.commission_rate,
            stamp_tax_rate=config.stamp_tax_rate,
            slippage_bps=config.slippage_bps,
            minimum_commission=config.minimum_commission,
            transfer_fee_rate=config.transfer_fee_rate,
        )

    def sell_real(
        symbol: str,
        pos: _Position,
        exit_date: str,
        exit_price: float,
        volume: int,
        reason: str,
    ) -> None:
        nonlocal cash
        execution = sell_execution(exit_price, volume, pos.buy_price)
        cash += execution.cash_delta
        total_vol = pos.initial_volume or pos.volume
        sell_cost = pos.cash_cost * (volume / total_vol) if total_vol else pos.cash_cost
        net_pnl = execution.cash_delta - sell_cost
        closed_trades.append(
            {
                "vt_symbol": symbol,
                "name": pos.name or symbol,
                "entry_date": pos.entry_date,
                "exit_date": exit_date,
                "buy_price": pos.buy_price,
                "buy_time": pos.buy_time,
                "exit_price": execution.price,
                "volume": volume,
                "sell_amount": execution.amount,
                "fee": execution.fee,
                "net_pnl": net_pnl,
                "return_pct": round(net_pnl / sell_cost * 100, 4) if sell_cost else None,
                "is_win": net_pnl > 0,
                "exit_reason": reason,
                "board_status": pos.board_status,
            }
        )

    def sell_paper(paper: _PaperPosition, exit_price: float, volume: int) -> None:
        execution = sell_execution(exit_price, volume, paper.buy_price)
        total_vol = paper.initial_volume or paper.volume
        sell_cost = (
            paper.cash_cost * (volume / total_vol) if total_vol else paper.cash_cost
        )
        paper.net_pnl += execution.cash_delta - sell_cost

    def finish_paper(paper: _PaperPosition) -> None:
        paper.sample["is_leader"] = paper.net_pnl > 0

    for today in calendar:
        prev_day = prev_map[today]
        today_date = date.fromisoformat(today)
        # ── 1) D+1 卖出：真实持仓 + paper 持仓（同一套日线规则）
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            bar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
            if not bar or not prev_bar:
                continue
            prev_close = _float(prev_bar.get("close_price")) or 0.0
            if prev_close <= 0:
                continue
            kind, price = _d1_exit(bar, prev_close)
            if kind == "limit_close":
                sell_vol = (pos.volume // 2 // config.lot_size) * config.lot_size
                if sell_vol > 0:
                    sell_real(symbol, pos, today, price, sell_vol, "limit_half")
                    pos.volume -= sell_vol
                if pos.volume <= 0:
                    del positions[symbol]
            else:
                sell_real(symbol, pos, today, price, pos.volume, kind)
                del positions[symbol]
        for symbol in list(paper_positions.keys()):
            paper = paper_positions[symbol]
            bar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
            if not bar or not prev_bar:
                continue
            prev_close = _float(prev_bar.get("close_price")) or 0.0
            if prev_close <= 0:
                continue
            kind, price = _d1_exit(bar, prev_close)
            if kind == "limit_close":
                sell_vol = (paper.volume // 2 // config.lot_size) * config.lot_size
                if sell_vol > 0:
                    sell_paper(paper, price, sell_vol)
                    paper.volume -= sell_vol
                if paper.volume <= 0:
                    finish_paper(paper)
                    del paper_positions[symbol]
            else:
                sell_paper(paper, price, paper.volume)
                finish_paper(paper)
                del paper_positions[symbol]
        # ── 2) D 日全市场触发扫描（仅宽覆盖日）
        stats["days_total"] += 1
        window_bars = minute_loader(today_date)
        coverage = len(window_bars)
        stats["coverage_total"] += coverage
        if coverage < min_day_coverage:
            stats["days_skipped_low_coverage"] += 1
        else:
            stats["days_tradeable"] += 1
            month = today[:7]
            if month not in calibrations:
                calibrations[month] = _build_month_calibration(
                    train_samples,
                    month,
                    min_train_samples=min_train_samples,
                    min_effect=min_effect,
                )
                if calibrations[month]:
                    stats["calibration_months"] += 1
            calibration = calibrations[month]
            candidates: list[dict[str, object]] = []
            for symbol, bars in window_bars.items():
                if not _is_main_board(symbol):
                    continue
                name = names.get(symbol) or symbol
                if "ST" in name.upper():
                    continue
                dates = symbol_dates.get(symbol) or []
                index = bisect_left(dates, today)
                factors = _d1_factors(list(bars_by_symbol[symbol])[:index][-6:])
                if factors is None:
                    continue
                dbar = daily_index.get((symbol, today))
                prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
                if not dbar or not prev_bar:
                    continue
                open_price = _float(dbar.get("open_price")) or 0.0
                prev_close = _float(prev_bar.get("close_price")) or 0.0
                trigger = _trigger_buy(
                    bars,
                    open_price=open_price,
                    prev_close=prev_close,
                    surge_pct=surge_pct,
                    cum_pct=cum_pct,
                    window_start=window_start,
                    window_end=window_end,
                )
                if not trigger:
                    continue
                stats["trigger_count"] += 1
                sample: dict[str, object] = {
                    **factors,
                    "vt_symbol": symbol,
                    "name": name,
                    "trade_date": today,
                    "month": month,
                    "buy_price": trigger["buy_price"],
                    "buy_time": trigger["buy_time"],
                    "cum_pct": trigger["cum_pct"],
                    "board_status": _board_status(dbar, prev_close),
                    "is_leader": None,
                    "bought": False,
                    "score": None,
                }
                candidates.append(sample)
                # paper 单位持仓（训练标签，独立同规则模拟，不进真实账户）
                if symbol not in paper_positions:
                    paper_buy = cash_ledger.calculate_buy_execution(
                        raw_price=float(trigger["buy_price"]),
                        cash=PAPER_NOTIONAL,
                        target_cash=PAPER_NOTIONAL,
                        commission_rate=config.commission_rate,
                        slippage_bps=config.slippage_bps,
                        lot_size=config.lot_size,
                        minimum_commission=config.minimum_commission,
                        transfer_fee_rate=config.transfer_fee_rate,
                    )
                    if paper_buy.volume > 0:
                        paper_positions[symbol] = _PaperPosition(
                            sample=sample,
                            volume=paper_buy.volume,
                            buy_price=paper_buy.price,
                            cash_cost=paper_buy.amount + paper_buy.fee,
                            initial_volume=paper_buy.volume,
                        )
            # ── 3) 校准排序 + TOP N 买入
            if calibration:
                for sample in candidates:
                    sample["score"] = score_leader_probability(sample, calibration)
                candidates.sort(
                    key=lambda s: (
                        -(s["score"] if s["score"] is not None else float("-inf")),
                        -float(s["cum_pct"]),
                    )
                )
            else:
                candidates.sort(key=lambda s: -float(s["cum_pct"]))
            train_samples.extend(candidates)
            for sample in candidates:
                if len(positions) >= config.max_positions:
                    break
                symbol = str(sample["vt_symbol"])
                if symbol in positions:
                    continue
                total_equity_now = cash + sum(
                    p.volume * daily_close(s, today) for s, p in positions.items()
                )
                buy = cash_ledger.calculate_buy_execution(
                    raw_price=float(sample["buy_price"]),
                    cash=cash,
                    target_cash=total_equity_now / config.max_positions,
                    commission_rate=config.commission_rate,
                    slippage_bps=config.slippage_bps,
                    lot_size=config.lot_size,
                    minimum_commission=config.minimum_commission,
                    transfer_fee_rate=config.transfer_fee_rate,
                )
                if buy.volume <= 0:
                    continue
                cash = buy.cash_after
                sample["bought"] = True
                positions[symbol] = _Position(
                    symbol,
                    buy.volume,
                    today,
                    buy.price,
                    name=str(sample["name"]),
                    buy_time=str(sample["buy_time"]),
                    cash_cost=buy.amount + buy.fee,
                    initial_volume=buy.volume,
                    board_status=str(sample["board_status"]),
                )
        # ── 4) equity mark（用当日收盘，盘后行为非决策）
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

    # ── 5) 末日清仓（真实 + paper）
    last_day = calendar[-1] if calendar else ""
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        bar = daily_index.get((symbol, last_day))
        exit_price = (_float(bar.get("close_price")) or pos.buy_price) if bar else pos.buy_price
        sell_real(symbol, pos, last_day, exit_price, pos.volume, "final_close")
        del positions[symbol]
    for symbol in list(paper_positions.keys()):
        paper = paper_positions[symbol]
        bar = daily_index.get((symbol, last_day))
        exit_price = (_float(bar.get("close_price")) or paper.buy_price) if bar else paper.buy_price
        sell_paper(paper, exit_price, paper.volume)
        finish_paper(paper)
        del paper_positions[symbol]

    labeled = [s for s in train_samples if s.get("is_leader") is not None]
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
        "coverage_stats": {
            "days_total": stats["days_total"],
            "days_tradeable": stats["days_tradeable"],
            "days_skipped_low_coverage": stats["days_skipped_low_coverage"],
            "avg_covered_symbols": round(
                stats["coverage_total"] / stats["days_total"], 1
            )
            if stats["days_total"]
            else 0,
            "trigger_count": stats["trigger_count"],
            "calibration_months": stats["calibration_months"],
            "train_samples_labeled": len(labeled),
            "label_win_count": sum(1 for s in labeled if s.get("is_leader")),
        },
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


def run_minute_backtest(
    *,
    start: date,
    end: date,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
    min_day_coverage: int = MIN_DAY_COVERAGE,
) -> dict[str, object]:
    """加载全市场日线 + 分钟 bar，跑无未来函数的全市场分钟级回测。"""

    daily_bars = load_daily_bars_all(start - timedelta(days=20), end + timedelta(days=7))
    names = load_stock_names()
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for rows in bars_by_symbol.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    daily_index = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")): bar
        for bar in daily_bars
    }
    calendar = sorted(
        {
            str(bar.get("trade_date") or "")
            for bar in daily_bars
            if bar.get("trade_date")
            and start.isoformat() <= str(bar["trade_date"]) <= end.isoformat()
        }
    )
    result = simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=calendar,
        names=names,
        minute_loader=load_window_minute_bars,
        surge_pct=surge_pct,
        cum_pct=cum_pct,
        min_day_coverage=min_day_coverage,
    )
    stats = result["coverage_stats"]
    result["study_version"] = STUDY_VERSION
    result["start"] = start.isoformat()
    result["end"] = end.isoformat()
    result["surge_pct"] = surge_pct
    result["cum_pct"] = cum_pct
    result["window"] = f"{WINDOW_START}-{WINDOW_END}"
    result["notes"] = [
        "v2 修复 v1 样本选择偏差：universe=当日有分钟数据的全市场主板非ST股票，不再从事后涨停池出发。",
        "触发/封板/一字全部盘中可观测：9:31-9:40 surge≥2% 或 cum≥7% 按触发 bar close 买入；触发 bar close≥涨停价 或 开盘≥涨停价跳过（不用 events 的 first_limit_time）。",
        f"仅在分钟覆盖≥{min_day_coverage}票的宽覆盖日交易：{stats['days_tradeable']}/{stats['days_total']} 天（稀疏日多为事件票回填，整日跳过以消除覆盖偏差）。",
        "4 个因子全部 D-1：流通市值(D-1成交额/换手率推导)、前5日涨幅、前3日上涨天数、前5日量比；触发群体月度 expanding 校准，标签=D+1净赢，训练只用之前完整月。",
        "剩余限制：宽覆盖日的未覆盖票（约 2/3）中的触发被漏掉，覆盖偏活跃股；结论代表「有分钟数据的全市场子集」，非绝对全市场。",
    ]
    return result


def main(argv: Sequence[str] | None = None) -> None:
    """Run the all-market minute backtest and write to DB."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--surge-pct", type=float, default=DEFAULT_SURGE_PCT)
    parser.add_argument("--cum-pct", type=float, default=DEFAULT_CUM_PCT)
    parser.add_argument("--min-day-coverage", type=int, default=MIN_DAY_COVERAGE)
    parser.add_argument("--json-output", type=Path, required=False)
    arguments = parser.parse_args(argv)

    result = run_minute_backtest(
        start=arguments.start,
        end=arguments.end,
        surge_pct=arguments.surge_pct,
        cum_pct=arguments.cum_pct,
        min_day_coverage=arguments.min_day_coverage,
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
