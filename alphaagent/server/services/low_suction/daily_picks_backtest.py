"""低吸日线回测报告构建：分数段统计 + 两仓位模拟 + 交割单。

输入为扫描器产出的全窗口候选清单，输出可持久化的 JSON payload。
口径与研究一致：D+1 收盘到收盘、未扣费、raw_unadjusted 探索级。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean, median

from alphaagent.server.services.low_suction.daily_factor_research import (
    split_market_calendar,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import SCORE_BANDS


BACKTEST_VERSION = "low-suction-daily-backtest-v1"
RECENT_LEDGER_DAYS = 60
_MIN_BAND_SAMPLE = 30


def build_backtest_payload(
    candidates: list[LowSuctionCandidate],
    calendar: list[date] | tuple[date, ...],
    *,
    names: dict[str, str] | None = None,
) -> dict[str, object]:
    """Build the materialized backtest report from scored candidates."""

    labeled = [item for item in candidates if item.d1_close_return_pct is not None]
    split = split_market_calendar(list(calendar))
    segment_by_date: dict[date, str] = {}
    for value in split.development_dates:
        segment_by_date[value] = "development"
    for value in split.validation_dates:
        segment_by_date[value] = "validation"
    for value in split.holdout_dates:
        segment_by_date[value] = "holdout"

    families: dict[str, object] = {}
    for setup_type in ("trend_pullback", "oversold_rebound"):
        pool = [item for item in labeled if item.setup_type == setup_type]
        families[setup_type] = _family_report(pool, segment_by_date)

    position = _position_simulation(labeled)
    ledger_days = _recent_ledger(position["trades"], names or {})

    return {
        "version": BACKTEST_VERSION,
        "label_convention": "D+1 收盘到收盘，未扣费，raw_unadjusted 探索级",
        "coverage": {
            "calendar_start": calendar[0].isoformat() if calendar else None,
            "calendar_end": calendar[-1].isoformat() if calendar else None,
            "trade_days": len(calendar),
            "candidates": len(candidates),
            "labeled": len(labeled),
        },
        "time_split": {
            "development": _segment_range(split.development_dates),
            "validation": _segment_range(split.validation_dates),
            "holdout": _segment_range(split.holdout_dates),
        },
        "families": families,
        "position_sim": {
            "trend_pullback": _sim_summary(position, "trend_pullback"),
            "oversold_rebound": _sim_summary(position, "oversold_rebound"),
            "combined": position["combined"],
            "equity_curve": position["equity_curve"],
        },
        "ledger_days": ledger_days,
    }


def _family_report(
    pool: list[LowSuctionCandidate],
    segment_by_date: dict[date, str],
) -> dict[str, object]:
    bands: dict[str, object] = {}
    for _, _, band in SCORE_BANDS:
        members = [item for item in pool if item.band == band]
        if len(members) < _MIN_BAND_SAMPLE:
            continue
        by_day: dict[date, list[float]] = defaultdict(list)
        by_segment: dict[str, list[float]] = defaultdict(list)
        for item in members:
            value = float(item.d1_close_return_pct)  # type: ignore[arg-type]
            by_day[item.trade_date].append(value)
            by_segment[segment_by_date.get(item.trade_date, "embargo")].append(value)
        equity = 1.0
        for day in sorted(by_day):
            equity *= 1 + mean(by_day[day]) / 100
        full_values = [float(item.d1_close_return_pct) for item in members]  # type: ignore[arg-type]
        segment_stats = {
            segment: _stats(values) for segment, values in sorted(by_segment.items())
        }
        # 推荐区间判定与正式 qualification gate 同口径：validation+holdout 双段为正
        validation_mean = (segment_stats.get("validation") or {}).get("mean_pct")
        holdout_mean = (segment_stats.get("holdout") or {}).get("mean_pct")
        recommended = bool(
            validation_mean is not None
            and validation_mean > 0
            and holdout_mean is not None
            and holdout_mean > 0
        )
        bands[band] = {
            "n": len(members),
            "win_rate_pct": _win_rate(full_values),
            "mean_pct": round(mean(full_values), 4),
            "median_pct": round(median(full_values), 4),
            "compound_pct": round((equity - 1) * 100, 2),
            "active_days": len(by_day),
            "segments": segment_stats,
            "recommended": recommended,
        }
    all_values = [float(item.d1_close_return_pct) for item in pool]  # type: ignore[arg-type]
    return {
        "total": _stats(all_values),
        "bands": bands,
    }


def _position_simulation(labeled: list[LowSuctionCandidate]) -> dict[str, object]:
    """每日各取分数最高的趋势/超跌一只，D+1 收盘结算，两仓各半。

    并列时用已验证的单调方向决胜：连续小 K 线越多越好、换手率越低越好
    （超跌族顶分并列率 93%，决胜键就是真实选择规则，必须固定且有意义）。
    """

    best: dict[str, dict[date, LowSuctionCandidate]] = {
        "trend_pullback": {},
        "oversold_rebound": {},
    }
    for item in labeled:
        slot = best[item.setup_type]
        current = slot.get(item.trade_date)
        if current is None or _pick_key(item) > _pick_key(current):
            slot[item.trade_date] = item

    trades: list[dict[str, object]] = []
    for setup_type in ("trend_pullback", "oversold_rebound"):
        for day in sorted(best[setup_type]):
            pick = best[setup_type][day]
            trades.append(
                {
                    "trade_date": day.isoformat(),
                    "d1_trade_date": pick.d1_trade_date.isoformat()
                    if pick.d1_trade_date
                    else None,
                    "vt_symbol": pick.vt_symbol,
                    "symbol": pick.vt_symbol.split(".")[0],
                    "setup_type": setup_type,
                    "rule_key": pick.rule_key,
                    "score": pick.score,
                    "band": pick.band,
                    "close_price": pick.close_price,
                    "d1_close_return_pct": pick.d1_close_return_pct,
                    "streak_total": pick.streak.total,
                }
            )

    days = sorted(set(best["trend_pullback"]) | set(best["oversold_rebound"]))
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    equity_curve: list[dict[str, object]] = []
    day_returns: list[float] = []
    for day in days:
        legs: list[float] = []
        for setup_type in ("trend_pullback", "oversold_rebound"):
            pick = best[setup_type].get(day)
            if pick is not None and pick.d1_close_return_pct is not None:
                legs.append(float(pick.d1_close_return_pct))
        day_return = sum(legs) / 2  # 两腿各半仓；缺腿半仓闲置
        equity *= 1 + day_return / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
        day_returns.append(day_return)
        equity_curve.append({"date": day.isoformat(), "equity": round(equity, 6)})

    per_family: dict[str, dict[str, object]] = {}
    for setup_type in ("trend_pullback", "oversold_rebound"):
        values = [
            float(pick.d1_close_return_pct)  # type: ignore[arg-type]
            for pick in best[setup_type].values()
            if pick.d1_close_return_pct is not None
        ]
        fam_equity = 1.0
        for value in values:
            fam_equity *= 1 + value / 100
        per_family[setup_type] = {
            **_stats(values),
            "trades": len(values),
            "compound_pct": round((fam_equity - 1) * 100, 2),
        }

    return {
        "trades": trades,
        "families": per_family,
        "combined": {
            **_stats(day_returns),
            "days": len(days),
            "compound_pct": round((equity - 1) * 100, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
        },
        "equity_curve": equity_curve,
    }


def _sim_summary(position: dict[str, object], setup_type: str) -> dict[str, object]:
    families = position["families"]  # type: ignore[index]
    return dict(families[setup_type])  # type: ignore[index]


def _pick_key(item: LowSuctionCandidate) -> tuple[float, int, float, str]:
    """并列决胜键：分数 → 连续小 K 线数 → 换手率(低优先) → 代码。"""

    return (
        item.score,
        item.streak.total,
        -(item.turnover_rate_pct if item.turnover_rate_pct is not None else 99.0),
        item.vt_symbol,
    )


def _recent_ledger(
    trades: list[dict[str, object]],
    names: dict[str, str],
) -> list[dict[str, object]]:
    """最近 N 个交易日的两仓交割单（最新在左由前端倒序）。"""

    by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        enriched = dict(trade)
        enriched["stock_name"] = names.get(str(trade["vt_symbol"]))
        by_day[str(trade["trade_date"])].append(enriched)
    days = sorted(by_day, reverse=True)[:RECENT_LEDGER_DAYS]
    result: list[dict[str, object]] = []
    for day in days:
        legs = sorted(by_day[day], key=lambda item: str(item["setup_type"]))
        day_return = sum(
            float(item["d1_close_return_pct"] or 0.0) for item in legs
        ) / 2
        result.append(
            {
                "trade_date": day,
                "d1_trade_date": legs[0]["d1_trade_date"] if legs else None,
                "day_return_pct": round(day_return, 4),
                "legs": legs,
            }
        )
    return result


def _segment_range(dates) -> dict[str, object]:
    values = list(dates)
    if not values:
        return {"start": None, "end": None, "days": 0}
    return {
        "start": values[0].isoformat(),
        "end": values[-1].isoformat(),
        "days": len(values),
    }


def _win_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0) / len(values) * 100, 2)


def _stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {"n": 0, "win_rate_pct": None, "mean_pct": None, "median_pct": None}
    return {
        "n": len(values),
        "win_rate_pct": _win_rate(values),
        "mean_pct": round(mean(values), 4),
        "median_pct": round(median(values), 4),
    }
