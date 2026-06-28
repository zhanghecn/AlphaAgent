"""Sector scoring algorithm — heat score, trend state, leader identification.

Reads from local PostgreSQL tables (sectors, sector_daily_bars,
sector_memberships, stock_daily_bars, sector_fund_flows, stock_events)
and writes computed results to sector_daily_metrics and sector_period_scores.

Design constraints:
  - No hardcoded sector templates; every score comes from data evidence.
  - Data-insufficient sectors return UNKNOWN / confidence=0 rather than faked scores.
  - Every computed record includes source, as_of_date, evidence, confidence.

Heat score formula (per plan section 7.1):
  heat_score = 0.25 * momentum_score
             + 0.15 * continuity_score
             + 0.15 * breadth_score
             + 0.15 * fund_score
             + 0.12 * sentiment_score
             + 0.13 * leader_score
             + 0.05 * liquidity_score
             - risk_penalty

Trend states: MAINLINE_UP, FAST_UP, ROTATION, FADING, WEAK, UNKNOWN.

Periods: 1d, 3d, 5d, 10d, 20d, 60d, 120d, 250d.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import and_, desc, func, select
from sqlalchemy.engine import Engine

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope

logger = logging.getLogger(__name__)

# ── Constants ──

PERIODS: tuple[str, ...] = ("1d", "3d", "5d", "10d", "20d", "60d", "120d", "250d")

PERIOD_TRADING_DAYS: dict[str, int] = {
    "1d": 1, "3d": 3, "5d": 5, "10d": 10,
    "20d": 20, "60d": 60, "120d": 120, "250d": 250,
}

# Heat score weights
W_MOMENTUM = 0.25
W_CONTINUITY = 0.15
W_BREADTH = 0.15
W_FUND = 0.15
W_SENTIMENT = 0.12
W_LEADER = 0.13
W_LIQUIDITY = 0.05

TREND_STATES = ("MAINLINE_UP", "FAST_UP", "ROTATION", "FADING", "WEAK", "UNKNOWN")

# Minimum data points required for each sub-score
MIN_BARS_FOR_SCORE = 5
MIN_MEMBERS_FOR_BREADTH = 3
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3000


# ── Data classes ──

@dataclass
class SectorScoreInput:
    """Collected input data for one sector over a given period."""

    sector_id: str
    sector_type: str
    period: str
    as_of_date: date

    # Price / returns
    bars: list[dict[str, Any]] = field(default_factory=list)
    return_pct: float | None = None

    # Membership breadth
    member_universe_count: int = 0
    member_bar_count: int = 0
    total_members: int = 0
    rise_count: int = 0
    fall_count: int = 0
    breadth_source: str | None = None

    # Fund flows
    main_net_inflow: float | None = None
    main_net_inflow_ratio: float | None = None

    # Sentiment (limit-up/down counts)
    limit_up_count: int = 0
    limit_down_count: int = 0
    sentiment_source: str | None = None

    # Leader
    leader_vt_symbol: str | None = None
    leader_name: str | None = None
    leader_change_pct: float | None = None
    leader_source: str | None = None

    # Liquidity
    total_turnover: float | None = None
    avg_daily_turnover: float | None = None


@dataclass
class SectorScoreResult:
    """Computed scores for one sector over one period."""

    sector_id: str
    as_of_date: date
    period: str
    sector_type: str

    return_pct: float | None = None
    rank_return: int | None = None

    momentum_score: float = 0.0
    continuity_score: float = 0.0
    breadth_score: float = 0.0
    fund_score: float = 0.0
    sentiment_score: float = 0.0
    leader_score: float = 0.0
    liquidity_score: float = 0.0
    risk_penalty: float = 0.0

    heat_score: float = 0.0
    trend_state: str = "UNKNOWN"
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)


# ── Main computation entry point ──

def compute_sector_period_scores(
    as_of_date: date | None = None,
    periods: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> list[SectorScoreResult]:
    """Compute period scores for all sectors, return results.

    Args:
        as_of_date: Score as of this date. Defaults to today.
        periods: Which periods to compute. Defaults to all.
        sector_limit: Max sectors to process (0 = all).

    Returns:
        List of SectorScoreResult, sorted by heat_score descending.
    """
    if not is_database_configured():
        logger.warning("Database not configured, skipping sector scores")
        return []

    if as_of_date is None:
        as_of_date = _default_score_as_of_date()
    if periods is None:
        periods = PERIODS

    # Load sectors from DB
    with session_scope() as session:
        sector_rows = session.execute(
            select(schema.sectors)
        ).mappings().all()

    if not sector_rows:
        logger.info("No sectors in DB for scoring")
        return []

    if sector_limit > 0:
        sector_rows = sector_rows[:sector_limit]

    all_results: list[SectorScoreResult] = []

    for sector_row in sector_rows:
        sector_id = str(sector_row["id"])
        sector_type = str(sector_row["type"])

        for period in periods:
            trading_days = PERIOD_TRADING_DAYS.get(period, 20)

            # Collect input data
            inp = _collect_score_input(sector_id, sector_type, as_of_date, trading_days)
            inp.period = period

            # Compute sub-scores
            result = _compute_single_score(inp)

            # Rank will be assigned after all results are collected
            all_results.append(result)

    # Assign return rank within each period
    _assign_return_ranks(all_results)

    return sorted(all_results, key=lambda r: r.heat_score, reverse=True)


def persist_scores(results: list[SectorScoreResult]) -> int:
    """Persist computed scores to sector_period_scores table."""
    if not results:
        return 0

    written = 0
    with session_scope() as session:
        for result in results:
            values = {
                "sector_id": result.sector_id,
                "as_of_date": result.as_of_date,
                "period": result.period,
                "sector_type": result.sector_type,
                "return_pct": result.return_pct,
                "rank_return": result.rank_return,
                "momentum_score": result.momentum_score,
                "breadth_score": result.breadth_score,
                "fund_score": result.fund_score,
                "sentiment_score": result.sentiment_score,
                "leader_score": result.leader_score,
                "continuity_score": result.continuity_score,
                "liquidity_score": result.liquidity_score,
                "risk_penalty": result.risk_penalty,
                "heat_score": result.heat_score,
                "trend_state": result.trend_state,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "source": "alphaagent.sector_scores",
                "computed_at": datetime.now(timezone.utc),
            }
            existing = session.execute(
                select(schema.sector_period_scores).where(
                    (schema.sector_period_scores.c.sector_id == result.sector_id)
                    & (schema.sector_period_scores.c.as_of_date == result.as_of_date)
                    & (schema.sector_period_scores.c.period == result.period)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_period_scores.update()
                    .where(
                        (schema.sector_period_scores.c.sector_id == result.sector_id)
                        & (schema.sector_period_scores.c.as_of_date == result.as_of_date)
                        & (schema.sector_period_scores.c.period == result.period)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.sector_period_scores.insert().values(**values))
            written += 1
    return written


def compute_and_persist(
    as_of_date: date | None = None,
    periods: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> dict[str, Any]:
    """Compute scores and persist. Returns summary."""
    resolved_as_of = as_of_date
    if resolved_as_of is None and is_database_configured():
        resolved_as_of = _default_score_as_of_date()
    results = compute_sector_period_scores(resolved_as_of, periods, sector_limit)
    written = persist_scores(results)
    return {
        "sectors_scored": len(results),
        "rows_written": written,
        "as_of_date": (resolved_as_of or date.today()).isoformat(),
    }


# ── Data collection ──

def _default_score_as_of_date() -> date:
    row = None
    with session_scope() as session:
        row = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= MIN_COMPLETE_DAILY_SYMBOL_COUNT)
            .order_by(desc(schema.stock_daily_bars.c.trade_date))
            .limit(1)
        ).first()
    return row[0] if row else date.today()


def _load_sector_members(session, sector_id: str) -> list[dict[str, Any]]:
    """Load the current member universe for a sector.

    Membership history is not versioned yet. The score still reads member price
    state strictly from ``as_of_date`` so breadth and leader do not use current
    quote snapshots.
    """
    rows = session.execute(
        select(
            schema.sector_memberships.c.vt_symbol,
            schema.sector_memberships.c.name,
        ).where(schema.sector_memberships.c.sector_id == sector_id)
    ).mappings().all()
    if rows:
        return _dedupe_members(rows)

    rows = session.execute(
        select(
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stocks.c.name,
        )
        .select_from(
            schema.stock_sector_memberships.outerjoin(
                schema.stocks,
                schema.stocks.c.vt_symbol == schema.stock_sector_memberships.c.vt_symbol,
            )
        )
        .where(schema.stock_sector_memberships.c.sector_id == sector_id)
    ).mappings().all()
    return _dedupe_members(rows)


def _dedupe_members(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    for row in rows:
        vt_symbol = row.get("vt_symbol")
        if not vt_symbol:
            continue
        symbol = str(vt_symbol)
        members.setdefault(symbol, {"vt_symbol": symbol, "name": row.get("name")})
    return list(members.values())


def _collect_member_daily_state(
    session,
    sector_id: str,
    as_of_date: date,
) -> dict[str, Any]:
    """Collect constituent breadth and leader from stock bars on as_of_date."""
    members = _load_sector_members(session, sector_id)
    member_names = {str(row["vt_symbol"]): row.get("name") for row in members}
    member_symbols = list(member_names)
    if not member_symbols:
        return {
            "member_symbols": [],
            "member_universe_count": 0,
            "member_bar_count": 0,
            "rise_count": 0,
            "fall_count": 0,
            "leader_vt_symbol": None,
            "leader_name": None,
            "leader_change_pct": None,
        }

    rows = session.execute(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.change_pct,
        ).where(
            and_(
                schema.stock_daily_bars.c.vt_symbol.in_(member_symbols),
                schema.stock_daily_bars.c.trade_date == as_of_date,
            )
        )
    ).mappings().all()

    daily_rows: list[dict[str, Any]] = []
    for row in rows:
        daily_rows.append({
            "vt_symbol": str(row["vt_symbol"]),
            "change_pct": _float_or_none(row.get("change_pct")),
        })

    change_rows = [row for row in daily_rows if row["change_pct"] is not None]
    leader_row = max(change_rows, key=lambda row: row["change_pct"], default=None)

    return {
        "member_symbols": member_symbols,
        "member_universe_count": len(member_symbols),
        "member_bar_count": len(daily_rows),
        "rise_count": sum(1 for row in change_rows if row["change_pct"] > 0),
        "fall_count": sum(1 for row in change_rows if row["change_pct"] < 0),
        "leader_vt_symbol": leader_row["vt_symbol"] if leader_row else None,
        "leader_name": member_names.get(leader_row["vt_symbol"]) if leader_row else None,
        "leader_change_pct": leader_row["change_pct"] if leader_row else None,
    }


def _count_limit_up_events(
    session,
    member_symbols: Sequence[str],
    as_of_date: date,
) -> int:
    if not member_symbols:
        return 0
    event_dates = [as_of_date.isoformat(), as_of_date.strftime("%Y%m%d")]
    count = session.execute(
        select(func.count(func.distinct(schema.stock_events.c.vt_symbol))).select_from(schema.stock_events)
        .where(
            and_(
                schema.stock_events.c.event_date.in_(event_dates),
                schema.stock_events.c.event_type == "limit_pool_zt",
                schema.stock_events.c.vt_symbol.in_(member_symbols),
            )
        )
    ).scalar()
    return int(count or 0)


def _aggregate_member_bars(session, sector_id: str, as_of_date: date, trading_days: int) -> list[dict[str, Any]]:
    """从成分股 K 线聚合板块指数（等权 close 均值），替代被反爬的 sector_daily_bars。

    sector_daily_bars（东财源）被反爬全空，改用 stock_daily_bars（腾讯源，稳定）+
    stock_sector_memberships（成分股映射）聚合算板块指数。return_pct 用 close，不受
    change_pct/turnover 缺失影响。
    """
    members = [row["vt_symbol"] for row in _load_sector_members(session, sector_id)]
    if not members:
        return []
    rows = session.execute(
        select(
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.turnover,
        )
        .where(
            and_(
                schema.stock_daily_bars.c.vt_symbol.in_(members),
                schema.stock_daily_bars.c.trade_date <= as_of_date,
            )
        )
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit((trading_days + 10) * len(members))
    ).mappings().all()
    if not rows:
        return []
    from collections import defaultdict

    closes_by_date: dict[Any, list[float]] = defaultdict(list)
    turnover_by_date: dict[Any, float] = defaultdict(float)
    for r in rows:
        d = r["trade_date"]
        if r["close_price"] is not None:
            closes_by_date[d].append(float(r["close_price"]))
        if r["turnover"]:
            turnover_by_date[d] += float(r["turnover"])
    bars: list[dict[str, Any]] = []
    for d in sorted(closes_by_date.keys(), reverse=True):
        cs = closes_by_date[d]
        if cs:
            bars.append({
                "trade_date": d,
                "close": sum(cs) / len(cs),
                "turnover": turnover_by_date.get(d, 0.0),
            })
            if len(bars) >= trading_days + 10:
                break
    return bars


def _collect_score_input(
    sector_id: str,
    sector_type: str,
    as_of_date: date,
    trading_days: int,
) -> SectorScoreInput:
    """Collect all input data needed for scoring one sector over N days."""
    inp = SectorScoreInput(
        sector_id=sector_id,
        sector_type=sector_type,
        period="",
        as_of_date=as_of_date,
    )

    with session_scope() as session:
        # 1. Sector daily bars (price history)
        bars_query = (
            select(schema.sector_daily_bars)
            .where(
                and_(
                    schema.sector_daily_bars.c.sector_id == sector_id,
                    schema.sector_daily_bars.c.trade_date <= as_of_date,
                )
            )
            .order_by(desc(schema.sector_daily_bars.c.trade_date))
            .limit(trading_days + 10)
        )
        bar_rows = session.execute(bars_query).mappings().all()
        inp.bars = [dict(r) for r in bar_rows]
        if not inp.bars:
            # sector_daily_bars（东财）被反爬全空时，从成分股聚合（腾讯源 stock_daily_bars，稳定）
            inp.bars = _aggregate_member_bars(session, sector_id, as_of_date, trading_days)

        # 2. Membership breadth and leader from member bars on as_of_date.
        member_state = _collect_member_daily_state(session, sector_id, as_of_date)
        inp.member_universe_count = int(member_state["member_universe_count"])
        inp.member_bar_count = int(member_state["member_bar_count"])
        inp.total_members = inp.member_bar_count
        inp.rise_count = int(member_state["rise_count"])
        inp.fall_count = int(member_state["fall_count"])
        inp.leader_vt_symbol = member_state["leader_vt_symbol"]
        inp.leader_name = member_state["leader_name"]
        inp.leader_change_pct = member_state["leader_change_pct"]
        inp.breadth_source = "stock_daily_bars.as_of_date"
        inp.leader_source = "stock_daily_bars.as_of_date"

        # 3. Fund flows (latest)
        fund_row = session.execute(
            select(schema.sector_fund_flows)
            .where(
                and_(
                    schema.sector_fund_flows.c.sector_id == sector_id,
                    schema.sector_fund_flows.c.trade_date <= as_of_date.isoformat(),
                )
            )
            .order_by(desc(schema.sector_fund_flows.c.trade_date))
            .limit(1)
        ).mappings().first()
        if fund_row:
            inp.main_net_inflow = fund_row.get("main_net_inflow")
            inp.main_net_inflow_ratio = fund_row.get("main_net_inflow_ratio")

        # 4. Limit-up events (sentiment)
        inp.limit_up_count = _count_limit_up_events(
            session,
            member_state["member_symbols"],
            as_of_date,
        )
        inp.sentiment_source = "stock_events.event_date"

    # Calculate return from bars
    inp.return_pct = _calculate_return_from_bars(inp.bars, trading_days)
    inp.total_turnover = _sum_turnover(inp.bars, trading_days)
    inp.avg_daily_turnover = (
        inp.total_turnover / max(trading_days, 1) if inp.total_turnover else None
    )

    return inp


# ── Score computation ──

def _compute_single_score(inp: SectorScoreInput) -> SectorScoreResult:
    """Compute all sub-scores and the final heat score for one sector/period."""
    result = SectorScoreResult(
        sector_id=inp.sector_id,
        as_of_date=inp.as_of_date,
        period=inp.period,
        sector_type=inp.sector_type,
        return_pct=inp.return_pct,
    )

    evidence: dict[str, Any] = {}
    confidence_factors: list[float] = []

    # Data sufficiency check
    bars_count = len(inp.bars)
    if bars_count < MIN_BARS_FOR_SCORE:
        result.trend_state = "UNKNOWN"
        result.confidence = 0.0
        result.evidence = {"reason": "insufficient_bars", "bars_available": bars_count, "min_required": MIN_BARS_FOR_SCORE}
        return result

    # ── 1. Momentum score (0-100) ──
    momentum, momentum_ev = _score_momentum(inp)
    result.momentum_score = momentum
    evidence["momentum"] = momentum_ev
    confidence_factors.append(min(bars_count / 20.0, 1.0))

    # ── 2. Continuity score (0-100) ──
    continuity, continuity_ev = _score_continuity(inp)
    result.continuity_score = continuity
    evidence["continuity"] = continuity_ev
    confidence_factors.append(min(bars_count / 30.0, 1.0))

    # ── 3. Breadth score (0-100) ──
    breadth, breadth_ev = _score_breadth(inp)
    result.breadth_score = breadth
    evidence["breadth"] = breadth_ev
    confidence_factors.append(1.0 if inp.total_members >= MIN_MEMBERS_FOR_BREADTH else 0.3)

    # ── 4. Fund score (0-100) ──
    fund, fund_ev = _score_fund(inp)
    result.fund_score = fund
    evidence["fund"] = fund_ev
    confidence_factors.append(1.0 if inp.main_net_inflow is not None else 0.2)

    # ── 5. Sentiment score (0-100) ──
    sentiment, sentiment_ev = _score_sentiment(inp)
    result.sentiment_score = sentiment
    evidence["sentiment"] = sentiment_ev
    confidence_factors.append(1.0 if inp.total_members > 0 else 0.1)

    # ── 6. Leader score (0-100) ──
    leader, leader_ev = _score_leader(inp)
    result.leader_score = leader
    evidence["leader"] = leader_ev
    confidence_factors.append(1.0 if inp.leader_change_pct is not None else 0.2)

    # ── 7. Liquidity score (0-100) ──
    liquidity, liquidity_ev = _score_liquidity(inp)
    result.liquidity_score = liquidity
    evidence["liquidity"] = liquidity_ev
    confidence_factors.append(1.0 if inp.avg_daily_turnover else 0.3)

    # ── Risk penalty (0-30) ──
    risk, risk_ev = _compute_risk_penalty(inp, momentum)
    result.risk_penalty = risk
    evidence["risk"] = risk_ev

    # ── Final heat score ──
    result.heat_score = (
        W_MOMENTUM * result.momentum_score
        + W_CONTINUITY * result.continuity_score
        + W_BREADTH * result.breadth_score
        + W_FUND * result.fund_score
        + W_SENTIMENT * result.sentiment_score
        + W_LEADER * result.leader_score
        + W_LIQUIDITY * result.liquidity_score
        - result.risk_penalty
    )

    # ── Confidence ──
    result.confidence = round(sum(confidence_factors) / len(confidence_factors), 2)

    # ── Trend state ──
    result.trend_state = _classify_trend_state(result, inp)
    result.evidence = evidence

    return result


# ── Sub-score functions ──

def _score_momentum(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on absolute return and relative outperformance.

    Returns (score 0-100, evidence_dict).
    """
    ret = inp.return_pct
    if ret is None:
        return 0.0, {"return_pct": None}

    # Map return to 0-100 scale
    # +10% => ~100, +5% => ~75, 0% => 50, -5% => ~25, -10% => 0
    raw_score = 50 + ret * 5.0
    score = max(0.0, min(100.0, raw_score))

    ev: dict[str, Any] = {"return_pct": round(ret, 4), "raw_score": round(raw_score, 2)}
    return round(score, 2), ev


def _score_continuity(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on ratio of up days and drawdown within period.

    Returns (score 0-100, evidence_dict).
    """
    if not inp.bars:
        return 0.0, {"bars": 0}

    trading_days = PERIOD_TRADING_DAYS.get(inp.period, 20)
    relevant_bars = inp.bars[:trading_days]
    if not relevant_bars:
        return 0.0, {"bars": 0}

    # Count up days
    up_days = sum(
        1 for b in relevant_bars
        if (b.get("change_pct") or 0) > 0
    )
    up_ratio = up_days / max(len(relevant_bars), 1)

    # Max drawdown from peak
    peak = 0.0
    max_dd = 0.0
    cumulative = 0.0
    for b in relevant_bars:
        cumulative += b.get("change_pct") or 0
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Score: up_ratio contributes 60%, drawdown penalty contributes 40%
    up_score = up_ratio * 100
    dd_penalty = min(max_dd * 10, 40)  # Max 40 penalty from drawdown
    score = max(0.0, min(100.0, up_score * 0.6 + (100 - dd_penalty) * 0.4))

    ev: dict[str, Any] = {
        "up_days": up_days,
        "total_days": len(relevant_bars),
        "up_ratio": round(up_ratio, 3),
        "max_drawdown_pct": round(max_dd, 4),
    }
    return round(score, 2), ev


def _score_breadth(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on rise/fall ratio among constituent stocks.

    Returns (score 0-100, evidence_dict).
    """
    total = inp.total_members
    if total < MIN_MEMBERS_FOR_BREADTH:
        return 0.0, {
            "total_members": total,
            "member_universe_count": inp.member_universe_count,
            "member_bar_count": inp.member_bar_count,
            "source": inp.breadth_source,
            "as_of_date": inp.as_of_date.isoformat(),
            "reason": "too_few_members",
        }

    rise = inp.rise_count
    fall = inp.fall_count
    rise_ratio = rise / max(total, 1)

    # Score: rise_ratio mapped to 0-100
    score = rise_ratio * 100

    ev: dict[str, Any] = {
        "total_members": total,
        "member_universe_count": inp.member_universe_count,
        "member_bar_count": inp.member_bar_count,
        "rise_count": rise,
        "fall_count": fall,
        "rise_ratio": round(rise_ratio, 3),
        "source": inp.breadth_source,
        "as_of_date": inp.as_of_date.isoformat(),
    }
    return round(max(0.0, min(100.0, score)), 2), ev


def _score_fund(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on fund net inflow direction and magnitude.

    Returns (score 0-100, evidence_dict).
    """
    net_inflow = inp.main_net_inflow
    net_ratio = inp.main_net_inflow_ratio

    if net_inflow is None:
        return 50.0, {"reason": "no_fund_data"}

    # Use net ratio if available, otherwise estimate from absolute value
    if net_ratio is not None:
        # net_ratio is typically in percentage; map to 0-100
        # +5% inflow => ~90, 0% => 50, -5% => ~10
        score = 50 + net_ratio * 8.0
    else:
        # Estimate from absolute net inflow (billion yuan scale)
        # Positive inflow => boost, negative => penalty
        score = 50 + min(max(net_inflow / 1e9 * 5.0, -50), 50)

    ev: dict[str, Any] = {
        "main_net_inflow": net_inflow,
        "main_net_inflow_ratio": net_ratio,
    }
    return round(max(0.0, min(100.0, score)), 2), ev


def _score_sentiment(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on limit-up/down counts among members.

    Returns (score 0-100, evidence_dict).
    """
    total = inp.total_members
    zt_count = inp.limit_up_count

    if total < MIN_MEMBERS_FOR_BREADTH:
        return 50.0, {
            "total_members": total,
            "member_universe_count": inp.member_universe_count,
            "member_bar_count": inp.member_bar_count,
            "source": inp.sentiment_source,
            "as_of_date": inp.as_of_date.isoformat(),
            "reason": "too_few_members",
        }

    zt_ratio = zt_count / max(total, 1)

    # Score: limit-up ratio contributes positively, up to 100
    # 5%+ limit-up rate is very strong
    score = min(zt_ratio * 1000, 100)  # 10% zt => 100

    ev: dict[str, Any] = {
        "limit_up_count": zt_count,
        "total_members": total,
        "limit_up_ratio": round(zt_ratio, 4),
        "source": inp.sentiment_source,
        "as_of_date": inp.as_of_date.isoformat(),
    }
    return round(max(0.0, min(100.0, score)), 2), ev


def _score_leader(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on leader stock performance.

    Returns (score 0-100, evidence_dict).
    """
    leader_change = inp.leader_change_pct

    if leader_change is None:
        return 50.0, {
            "source": inp.leader_source,
            "as_of_date": inp.as_of_date.isoformat(),
            "reason": "no_leader_data",
        }

    # Map leader change to score
    score = 50 + leader_change * 3.0

    ev: dict[str, Any] = {
        "leader_vt_symbol": inp.leader_vt_symbol,
        "leader_name": inp.leader_name,
        "leader_change_pct": leader_change,
        "source": inp.leader_source,
        "as_of_date": inp.as_of_date.isoformat(),
    }
    return round(max(0.0, min(100.0, score)), 2), ev


def _score_liquidity(inp: SectorScoreInput) -> tuple[float, dict[str, Any]]:
    """Score based on trading volume/turnover.

    Returns (score 0-100, evidence_dict).
    """
    avg_turnover = inp.avg_daily_turnover

    if avg_turnover is None:
        return 50.0, {"reason": "no_turnover_data"}

    # Score based on absolute turnover (billion yuan)
    # 10B+ daily => 100, 5B => 75, 1B => 50, 0.5B => 25, <0.1B => 5
    billion = avg_turnover / 1e8  # Convert from yuan to yi (hundred million)
    score = min(max(billion * 10, 5), 100)

    ev: dict[str, Any] = {
        "avg_daily_turnover": avg_turnover,
        "turnover_yi": round(billion, 2),
    }
    return round(score, 2), ev


def _compute_risk_penalty(
    inp: SectorScoreInput,
    momentum_score: float,
) -> tuple[float, dict[str, Any]]:
    """Compute risk penalty (0-30).

    Risk factors:
      - Overheated: momentum too high (>90) in short period
      - Breadth declining: low rise ratio despite high return
      - Fund divergence: return up but fund outflow
      - Small sample: too few members

    Returns (penalty 0-30, evidence_dict).
    """
    penalty = 0.0
    factors: list[str] = []

    # 1. Overheated
    if inp.period in ("1d", "3d", "5d") and momentum_score > 90:
        penalty += 5.0
        factors.append("short_term_overheated")

    # 2. Breadth declining
    if inp.return_pct is not None and inp.return_pct > 3.0 and inp.total_members > 0:
        rise_ratio = inp.rise_count / max(inp.total_members, 1)
        if rise_ratio < 0.4:
            penalty += 8.0
            factors.append("breadth_declining")

    # 3. Fund divergence
    if inp.return_pct is not None and inp.return_pct > 2.0:
        if inp.main_net_inflow is not None and inp.main_net_inflow < 0:
            penalty += 10.0
            factors.append("fund_divergence")

    # 4. Small sample
    if 0 < inp.total_members < 5:
        penalty += 7.0
        factors.append("small_sample")

    ev: dict[str, Any] = {"penalty": round(penalty, 2), "factors": factors}
    return round(min(penalty, 30.0), 2), ev


# ── Trend state classification ──

def _classify_trend_state(result: SectorScoreResult, inp: SectorScoreInput) -> str:
    """Classify the trend state based on sub-scores.

    MAINLINE_UP: high heat, high continuity, breadth expanding
    FAST_UP: very high momentum but risk penalty > 5
    ROTATION: medium heat (40-60), moderate scores across the board
    FADING: positive return but declining breadth/fund
    WEAK: low heat, negative return
    UNKNOWN: insufficient data
    """
    heat = result.heat_score
    momentum = result.momentum_score
    breadth = result.breadth_score
    fund = result.fund_score
    risk = result.risk_penalty
    continuity = result.continuity_score

    # Data insufficient
    if result.confidence < 0.3:
        return "UNKNOWN"

    # Strong positive
    if heat >= 70 and continuity >= 60 and breadth >= 60:
        return "MAINLINE_UP"

    # Fast/overheated
    if momentum >= 80 and risk >= 5:
        return "FAST_UP"

    # Fading: still positive momentum but breadth/fund declining
    if momentum >= 60 and (breadth < 40 or fund < 40):
        return "FADING"

    # Rotation: medium range
    if 40 <= heat <= 70:
        return "ROTATION"

    # Weak
    if heat < 40:
        return "WEAK"

    return "ROTATION"


# ── Helper functions ──

def _calculate_return_from_bars(
    bars: list[dict[str, Any]],
    trading_days: int,
) -> float | None:
    """Calculate cumulative return from daily bars over N trading days."""
    if not bars:
        return None

    relevant = bars[:trading_days]
    if len(relevant) < 2:
        # Single bar: use its change_pct
        if len(relevant) == 1:
            return relevant[0].get("change_pct")
        return None

    # Use close of latest bar vs close of bar N days ago
    latest_close = relevant[0].get("close_price") or relevant[0].get("close")
    oldest_close = relevant[-1].get("close_price") or relevant[-1].get("close")

    if latest_close and oldest_close and oldest_close != 0:
        return ((latest_close - oldest_close) / oldest_close) * 100

    return None


def _sum_turnover(
    bars: list[dict[str, Any]],
    trading_days: int,
) -> float | None:
    """Sum turnover over N trading days from bars."""
    if not bars:
        return None
    relevant = bars[:trading_days]
    total = sum(b.get("turnover") or 0 for b in relevant)
    return total if total > 0 else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str) and not value.strip():
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _assign_return_ranks(results: list[SectorScoreResult]) -> None:
    """Assign return rank within each period group."""
    from itertools import groupby

    # Group by period
    by_period: dict[str, list[SectorScoreResult]] = {}
    for r in results:
        by_period.setdefault(r.period, []).append(r)

    for period, group in by_period.items():
        # Sort by return_pct descending (None values last)
        sorted_group = sorted(
            group,
            key=lambda r: r.return_pct if r.return_pct is not None else float("-inf"),
            reverse=True,
        )
        for rank, r in enumerate(sorted_group, start=1):
            r.rank_return = rank


# ── Sector daily metrics computation ──

def compute_sector_daily_metrics(
    trade_date: date | None = None,
) -> dict[str, Any]:
    """Compute daily metrics for all sectors and persist to sector_daily_metrics."""
    if not is_database_configured():
        return {"status": "unavailable", "message": "Database not configured"}

    if trade_date is None:
        trade_date = date.today()

    trade_date_str = trade_date.isoformat()

    with session_scope() as session:
        sectors = session.execute(select(schema.sectors)).mappings().all()

    written = 0
    for sector_row in sectors:
        sector_id = str(sector_row["id"])

        with session_scope() as session:
            # Get members' daily bars for this date
            member_bars = session.execute(
                select(schema.stock_daily_bars)
                .where(
                    (schema.stock_daily_bars.c.trade_date == trade_date)
                    & (schema.stock_daily_bars.c.vt_symbol.in_(
                        select(schema.sector_memberships.c.vt_symbol)
                        .where(schema.sector_memberships.c.sector_id == sector_id)
                    ))
                )
            ).mappings().all()

        if not member_bars:
            continue

        bars = [dict(b) for b in member_bars]
        changes = [b.get("change_pct") for b in bars if b.get("change_pct") is not None]
        if not changes:
            continue

        rise_count = sum(1 for c in changes if c > 0)
        fall_count = sum(1 for c in changes if c < 0)
        flat_count = len(changes) - rise_count - fall_count

        avg_change = sum(changes) / len(changes)
        sorted_changes = sorted(changes)
        median_change = sorted_changes[len(sorted_changes) // 2]

        turnovers = [b.get("turnover") for b in bars if b.get("turnover")]
        total_turnover = sum(turnovers) if turnovers else None

        # Weighted average by turnover
        if turnovers and total_turnover:
            tw_change = sum(
                (b.get("change_pct") or 0) * (b.get("turnover") or 0)
                for b in bars
            ) / total_turnover
        else:
            tw_change = avg_change

        # Find leader (highest change_pct)
        leader_bar = max(bars, key=lambda b: b.get("change_pct") or float("-inf"))

        values = {
            "sector_id": sector_id,
            "trade_date": trade_date,
            "stock_count": len(bars),
            "rise_count": rise_count,
            "fall_count": fall_count,
            "flat_count": flat_count,
            "avg_change_pct": round(avg_change, 4),
            "median_change_pct": round(median_change, 4),
            "turnover_weighted_change_pct": round(tw_change, 4),
            "market_cap_weighted_change_pct": None,
            "turnover": total_turnover,
            "main_net_inflow": None,
            "main_net_inflow_ratio": None,
            "leader_vt_symbol": leader_bar.get("vt_symbol"),
            "leader_name": None,
            "leader_change_pct": leader_bar.get("change_pct"),
            "leader_reason": "top_change_pct",
            "source": "alphaagent.sector_metrics",
            "raw": {},
        }

        with session_scope() as session:
            existing = session.execute(
                select(schema.sector_daily_metrics).where(
                    (schema.sector_daily_metrics.c.sector_id == sector_id)
                    & (schema.sector_daily_metrics.c.trade_date == trade_date)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_daily_metrics.update()
                    .where(
                        (schema.sector_daily_metrics.c.sector_id == sector_id)
                        & (schema.sector_daily_metrics.c.trade_date == trade_date)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.sector_daily_metrics.insert().values(**values))
            written += 1

    return {
        "status": "ok",
        "trade_date": trade_date_str,
        "sectors_processed": len(sectors),
        "rows_written": written,
    }
