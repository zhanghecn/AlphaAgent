"""低吸日线回测报告构建：分数段统计 + 十槽位模拟 + 交割单。

输入为扫描器产出的全窗口候选清单，输出可持久化的 JSON payload。
口径与研究一致：D 日收盘买入、D+1 收盘结算，未扣费、raw_unadjusted 探索级。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from statistics import mean, median

from alphaagent.server.services.low_suction.daily_factor_research import (
    split_market_calendar,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
    candidate_ranking_key,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import (
    SCORE_BANDS,
    SCORE_VERSION,
)


BACKTEST_VERSION = "low-suction-daily-backtest-v4"
RECENT_LEDGER_DAYS = 60
_MIN_BAND_SAMPLE = 30
PICKS_PER_FAMILY = 5
SETUP_TYPES = ("trend_pullback", "oversold_rebound")
MAX_POSITIONS = len(SETUP_TYPES) * PICKS_PER_FAMILY
ALLOCATION_PER_PICK_PCT = 100 / MAX_POSITIONS


def build_backtest_payload(
    candidates: list[LowSuctionCandidate],
    calendar: list[date] | tuple[date, ...],
    *,
    names: dict[str, str] | None = None,
    market_regimes: Mapping[date, str] | None = None,
) -> dict[str, object]:
    """Build the materialized report from scored candidates and fixed top-five picks."""

    labeled = [item for item in candidates if item.d1_close_return_pct is not None]
    split = split_market_calendar(list(calendar))
    segment_by_date: dict[date, str] = {}
    for value in split.development_dates:
        segment_by_date[value] = "development"
    for value in split.embargo_dates:
        segment_by_date[value] = "embargo"
    for value in split.validation_dates:
        segment_by_date[value] = "validation"
    for value in split.holdout_dates:
        segment_by_date[value] = "holdout"

    families: dict[str, object] = {}
    for setup_type in SETUP_TYPES:
        pool = [item for item in labeled if item.setup_type == setup_type]
        families[setup_type] = _family_report(pool, segment_by_date)

    position = _position_simulation(
        candidates,
        segment_by_date=segment_by_date,
        market_regimes=market_regimes or {},
    )
    ledger_days = _recent_ledger(position["trades"], names or {})

    return {
        "version": BACKTEST_VERSION,
        "score_version": SCORE_VERSION,
        "label_convention": (
            "D 日收盘买入、D+1 收盘结算，未扣费，raw_unadjusted 探索级；"
            "每族最高 5 只、每票 10%，未满 10 槽位留现金"
        ),
        "coverage": {
            "calendar_start": calendar[0].isoformat() if calendar else None,
            "calendar_end": calendar[-1].isoformat() if calendar else None,
            "trade_days": len(calendar),
            "candidates": len(candidates),
            "labeled": len(labeled),
        },
        "time_split": {
            "development": _segment_range(split.development_dates),
            "embargo": _segment_range(split.embargo_dates),
            "validation": _segment_range(split.validation_dates),
            "holdout": _segment_range(split.holdout_dates),
        },
        "selection": {
            "picks_per_family": PICKS_PER_FAMILY,
            "max_positions": MAX_POSITIONS,
            "allocation_per_pick_pct": ALLOCATION_PER_PICK_PCT,
            "unfilled_slots_are_cash": True,
        },
        "market_regime": {
            "index_vt_symbol": "000001.SSE",
            "definition": "信号日上证指数收盘相对当日 MA20（收盘后生成信号，D+1 结算）",
            "labels": {
                "above_ma20": "指数在 MA20 上方",
                "below_ma20": "指数在 MA20 下方",
                "unclassified": "指数数据不足",
            },
        },
        "families": families,
        "position_sim": {
            "trend_pullback": _sim_summary(position, "trend_pullback"),
            "oversold_rebound": _sim_summary(position, "oversold_rebound"),
            "combined": position["combined"],
            "time_segments": position["time_segments"],
            "market_regimes": position["market_regimes"],
            "equity_curve": position["equity_curve"],
        },
        "ledger_days": ledger_days,
    }


def _family_report(
    pool: list[LowSuctionCandidate],
    segment_by_date: Mapping[date, str],
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
        full_values = [
            float(item.d1_close_return_pct) for item in members
        ]  # type: ignore[arg-type]
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
    all_values = [
        float(item.d1_close_return_pct) for item in pool
    ]  # type: ignore[arg-type]
    return {
        "total": _stats(all_values),
        "bands": bands,
    }


def _position_simulation(
    candidates: list[LowSuctionCandidate],
    *,
    segment_by_date: Mapping[date, str],
    market_regimes: Mapping[date, str],
) -> dict[str, object]:
    """D 日先按同一决胜键取前五；D+1 标签只用于后续收益汇总。"""

    grouped: dict[str, dict[date, list[LowSuctionCandidate]]] = {
        setup_type: defaultdict(list) for setup_type in SETUP_TYPES
    }
    for item in candidates:
        grouped[item.setup_type][item.trade_date].append(item)

    selected: dict[str, dict[date, list[LowSuctionCandidate]]] = {
        setup_type: {
            day: sorted(items, key=candidate_ranking_key)[:PICKS_PER_FAMILY]
            for day, items in by_day.items()
        }
        for setup_type, by_day in grouped.items()
    }

    trades: list[dict[str, object]] = []
    for setup_type in SETUP_TYPES:
        for day in sorted(selected[setup_type]):
            for rank, pick in enumerate(selected[setup_type][day], start=1):
                trades.append(
                    {
                        "trade_date": day.isoformat(),
                        "d1_trade_date": pick.d1_trade_date.isoformat()
                        if pick.d1_trade_date
                        else None,
                        "vt_symbol": pick.vt_symbol,
                        "symbol": pick.vt_symbol.split(".")[0],
                        "setup_type": setup_type,
                        "rank": rank,
                        "allocation_pct": ALLOCATION_PER_PICK_PCT,
                        "rule_key": pick.rule_key,
                        "score": pick.score,
                        "band": pick.band,
                        "close_price": pick.close_price,
                        "d1_close_return_pct": pick.d1_close_return_pct,
                        "streak_total": pick.streak.total,
                    }
                )

    days = sorted(set(selected["trend_pullback"]) | set(selected["oversold_rebound"]))
    equity = 1.0
    equity_curve: list[dict[str, object]] = []
    day_records: list[dict[str, object]] = []
    family_day_returns: dict[str, list[float]] = {
        setup_type: [] for setup_type in SETUP_TYPES
    }
    for day in days:
        positions: list[LowSuctionCandidate] = []
        for setup_type in SETUP_TYPES:
            family_picks = selected[setup_type].get(day, [])
            settled_picks = [
                pick for pick in family_picks if pick.d1_close_return_pct is not None
            ]
            values = [float(pick.d1_close_return_pct) for pick in settled_picks]
            if values:
                family_day_returns[setup_type].append(mean(values))
                positions.extend(settled_picks)
        if not positions:
            continue
        day_return = sum(
            float(pick.d1_close_return_pct)
            for pick in positions
            if pick.d1_close_return_pct is not None
        ) / MAX_POSITIONS
        equity *= 1 + day_return / 100
        day_records.append(
            {
                "trade_date": day,
                "return_pct": day_return,
                "positions": len(positions),
                "segment": segment_by_date.get(day, "embargo"),
                "market_regime": market_regimes.get(day, "unclassified"),
            }
        )
        equity_curve.append({"date": day.isoformat(), "equity": round(equity, 6)})

    per_family: dict[str, dict[str, object]] = {}
    for setup_type in SETUP_TYPES:
        values = [
            float(pick.d1_close_return_pct)
            for picks in selected[setup_type].values()
            for pick in picks
            if pick.d1_close_return_pct is not None
        ]
        family_returns = family_day_returns[setup_type]
        family_equity = 1.0
        for value in family_returns:
            family_equity *= 1 + value / 100
        per_family[setup_type] = {
            **_stats(values),
            "trades": len(values),
            "active_days": len(family_returns),
            "average_positions_per_day": round(len(values) / len(family_returns), 2)
            if family_returns
            else 0.0,
            "daily_mean_pct": round(mean(family_returns), 4)
            if family_returns
            else None,
            "compound_pct": round((family_equity - 1) * 100, 2),
        }

    time_segments = {
        key: _portfolio_summary(
            [record for record in day_records if record["segment"] == key]
        )
        for key in ("development", "embargo", "validation", "holdout")
    }
    regime_summaries = {
        key: _portfolio_summary(
            [record for record in day_records if record["market_regime"] == key]
        )
        for key in ("above_ma20", "below_ma20", "unclassified")
    }

    return {
        "trades": trades,
        "families": per_family,
        "combined": _portfolio_summary(day_records),
        "time_segments": time_segments,
        "market_regimes": regime_summaries,
        "equity_curve": equity_curve,
    }


def _sim_summary(position: dict[str, object], setup_type: str) -> dict[str, object]:
    families = position["families"]  # type: ignore[index]
    return dict(families[setup_type])  # type: ignore[index]


def _recent_ledger(
    trades: list[dict[str, object]],
    names: dict[str, str],
) -> list[dict[str, object]]:
    """最近 N 个交易日的十槽位交割单（最新在左由前端倒序）。"""

    by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        enriched = dict(trade)
        enriched["stock_name"] = names.get(str(trade["vt_symbol"]))
        by_day[str(trade["trade_date"])].append(enriched)
    days = sorted(by_day, reverse=True)[:RECENT_LEDGER_DAYS]
    result: list[dict[str, object]] = []
    for day in days:
        legs = sorted(
            by_day[day],
            key=lambda item: (str(item["setup_type"]), int(item.get("rank") or 0)),
        )
        day_return = sum(
            float(item["d1_close_return_pct"] or 0.0) for item in legs
        ) / MAX_POSITIONS
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


def _portfolio_summary(records: list[dict[str, object]]) -> dict[str, object]:
    """Summarize portfolio days; each return already includes idle-cash slots."""

    values = [float(record["return_pct"]) for record in records]
    positions = [int(record["positions"]) for record in records]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in values:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
    return {
        **_stats(values),
        "days": len(records),
        "positions": sum(positions),
        "average_positions_per_day": round(mean(positions), 2) if positions else 0.0,
        "average_deployed_pct": round(mean(positions) * ALLOCATION_PER_PICK_PCT, 2)
        if positions
        else 0.0,
        "compound_pct": round((equity - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
    }
