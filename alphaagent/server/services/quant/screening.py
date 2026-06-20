"""Database-backed quant screening orchestration."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards, stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.quant.factors import (
    DRAGON_PULLBACK_STRATEGY_ID,
    STRATEGY_ID,
    STRATEGY_VERSION,
    Bar,
    SignalScore,
)
from alphaagent.server.services.quant import candidate_lanes, market_context
from alphaagent.server.services.quant import screening_loaders, screening_payloads, screening_persistence
from alphaagent.server.services.quant.financials import financial_coverage_summary
from alphaagent.server.services.quant.strategy_registry import get_strategy, score_strategy


DEFAULT_RECOMMENDATION_LIMIT = 20
TAIL_PREVIEW_DATA_SOURCE = "intraday_snapshot_temp_bar"
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3000


@dataclass(frozen=True)
class _ScreenRangeContext:
    stock_rows: list[dict[str, Any]]
    stock_meta: dict[str, dict[str, Any]]
    symbols: list[str]
    bars_by_symbol: dict[str, list[Bar]]
    bar_dates_by_symbol: dict[str, list[date]]


def list_available_strategies() -> dict[str, Any]:
    from alphaagent.server.services.quant.strategy_registry import list_strategies

    items = list_strategies()
    return {"status": "ready", "items": items, "default_strategy_id": STRATEGY_ID}


def screen_stocks(
    trade_date: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    min_recommendation_score: float = 60.0,
    persist: bool = False,
    auto_portfolio: bool = True,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
    ensure_schema: bool = True,
    range_context: _ScreenRangeContext | None = None,
) -> dict[str, Any]:
    """Run the daily stock screen."""

    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": [], "recommendations": []}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": [], "recommendations": []}
    if ensure_schema:
        _ensure_quant_schema()

    with session_scope() as session:
        as_of = trade_date or _latest_trade_date(session)
        if as_of is None:
            return {"status": "empty", "message": "stock_daily_bars is empty", "items": [], "recommendations": []}

        boards = normalize_included_boards(included_boards)
        if range_context is not None:
            stock_rows = range_context.stock_rows
            symbols = range_context.symbols
            bars_by_symbol = range_context.bars_by_symbol
            bar_dates_by_symbol = range_context.bar_dates_by_symbol
        else:
            stock_rows = _load_stock_universe(session, max_symbols, boards)
            symbols = [str(row["vt_symbol"]) for row in stock_rows]
            bars_by_symbol = _load_bars(session, symbols, as_of, lookback_days=160)
            bar_dates_by_symbol = _bar_dates_by_symbol(bars_by_symbol)
        index_return_20d = _load_index_return_20d(session, as_of)
        market_payload = market_context.market_context_for_date(session, schema, as_of)
        sector_scores = _load_sector_scores(session, symbols, as_of)
        financial_scores = _load_financial_scores(session, symbols, as_of)
        fund_flow_scores = _load_fund_flow_scores(session, symbols, as_of)
        hot_rank_scores = _load_hot_rank_scores(session, symbols, as_of)
        lhb_scores = _load_lhb_scores(session, symbols, as_of)

        scored = []
        stock_meta = {str(row["vt_symbol"]): dict(row) for row in stock_rows}
        for vt_symbol in symbols:
            bars = _visible_bars_for_date(
                bars_by_symbol.get(vt_symbol, []),
                bar_dates_by_symbol.get(vt_symbol, []),
                as_of,
            )
            if not bars:
                continue
            score = score_strategy(
                strategy.id,
                vt_symbol,
                bars,
                as_of,
                index_return_20d=index_return_20d,
                sector_score=sector_scores.get(vt_symbol),
                financial_score=financial_scores.get(vt_symbol),
                fund_flow_score=fund_flow_scores.get(vt_symbol),
                hot_rank_score=hot_rank_scores.get(vt_symbol),
                lhb_score=lhb_scores.get(vt_symbol),
            )
            if score.evidence.get("status") == "ready":
                # 信号日收盘价随 evidence 存储，供买卖计划预算与单股回测复用（免重算）
                score.evidence["close_price"] = float(bars[-1].close_price)
                _attach_market_context(score, market_payload)
                scored.append(score)

        scored.sort(key=lambda item: (-item.total_score, item.vt_symbol))
        recommendations = [
            item
            for item in scored
            if item.entry_signal or item.total_score >= min_recommendation_score
        ]
        recommendations = _select_recommendations(
            recommendations,
            strategy.id,
            strategy.default_min_entry_score,
            recommendation_limit,
        )
        run_id = None
        portfolio_sync = None
        if persist:
            run_id = _persist_screen_run(session, as_of, scored, recommendations, strategy.id, strategy.version, boards, max_symbols=max_symbols)
            if auto_portfolio:
                portfolio_sync = _sync_quant_candidate_group(session, recommendations, stock_meta, strategy.id, strategy.version)

    return {
        "status": "ready" if scored else "empty",
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "trade_date": as_of.isoformat(),
        "run_id": run_id,
        "items": [_score_to_api(item, stock_meta.get(item.vt_symbol)) for item in scored],
        "recommendations": [
            _recommendation_to_api(index + 1, item, stock_meta.get(item.vt_symbol))
            for index, item in enumerate(recommendations)
        ],
        "total": len(scored),
        "recommendation_count": len(recommendations),
        "included_boards": list(boards),
        "portfolio_sync": portfolio_sync,
    }


_SCREEN_STOCKS_IMPL = screen_stocks


def screen_tail_preview(
    trade_date: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    recommendation_limit: int = 100,
    min_recommendation_score: float = 60.0,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
) -> dict[str, Any]:
    """Score today's tail candidates from complete daily bars plus live snapshot prices.

    This is intentionally read-only. It does not persist quant_signal_runs, does not
    sync the portfolio candidate group, and must not be used by historical backtests.
    """

    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": [], "recommendations": []}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": [], "recommendations": []}
    _ensure_quant_schema()

    with session_scope() as session:
        latest_daily_date = _latest_trade_date(session)
        base_daily_date = _latest_complete_trade_date(session) or latest_daily_date
        snapshot_updated_at = _latest_snapshot_updated_at(session)
        snapshot_trade_time = _latest_snapshot_trade_time(session)
        latest_intraday_date = _latest_tail_intraday_trade_date(session, base_daily_date)
        as_of = trade_date or latest_intraday_date
        as_of_daily_symbol_count = _daily_symbol_count(session, as_of) if as_of else 0
        if base_daily_date is None:
            return {"status": "empty", "message": "stock_daily_bars is empty", "items": [], "recommendations": []}
        if as_of is None:
            return _tail_preview_waiting_payload(
                strategy,
                base_daily_date=base_daily_date,
                latest_daily_date=latest_daily_date,
                latest_intraday_date=latest_intraday_date,
                snapshot_updated_at=snapshot_updated_at,
                snapshot_trade_time=snapshot_trade_time,
                message="暂无晚于最新完整日线的盘中分钟线，不能生成新的尾盘预览。",
            )
        if as_of <= base_daily_date and as_of_daily_symbol_count >= MIN_COMPLETE_DAILY_SYMBOL_COUNT:
            return {
                "status": "complete_daily_available",
                "message": "完整日线已覆盖该日期，请使用历史候选。",
                "strategy_id": strategy.id,
                "strategy_version": strategy.version,
                "trade_date": as_of.isoformat(),
                "base_daily_date": base_daily_date.isoformat(),
                "items": [],
                "recommendations": [],
                "total": 0,
                "recommendation_count": 0,
            }
        if not _tail_intraday_date_available(session, as_of):
            return _tail_preview_waiting_payload(
                strategy,
                trade_date=as_of,
                base_daily_date=base_daily_date,
                latest_daily_date=latest_daily_date,
                latest_intraday_date=latest_intraday_date,
                snapshot_updated_at=snapshot_updated_at,
                snapshot_trade_time=snapshot_trade_time,
                message="目标日期没有盘中分钟线，不能只用快照写库时间生成尾盘预览。",
            )

        boards = normalize_included_boards(included_boards)
        stock_rows = _load_stock_universe(session, max_symbols, boards)
        symbols = [str(row["vt_symbol"]) for row in stock_rows]
        bars_by_symbol = _load_bars(session, symbols, base_daily_date, lookback_days=160)
        bar_dates_by_symbol = _bar_dates_by_symbol(bars_by_symbol)
        intraday_bars = _load_intraday_temp_bars(session, symbols, as_of)
        index_return_20d = _load_index_return_20d(session, base_daily_date)
        market_payload = market_context.market_context_for_date(session, schema, base_daily_date)
        sector_scores = _load_sector_scores(session, symbols, base_daily_date)
        financial_scores = _load_financial_scores(session, symbols, base_daily_date)
        fund_flow_scores = _load_fund_flow_scores(session, symbols, base_daily_date)
        hot_rank_scores = _load_hot_rank_scores(session, symbols, base_daily_date)
        lhb_scores = _load_lhb_scores(session, symbols, base_daily_date)

        stock_meta = {str(row["vt_symbol"]): dict(row) for row in stock_rows}
        scored: list[SignalScore] = []
        snapshot_price_count = 0
        intraday_bar_count = 0
        for vt_symbol in symbols:
            stock = stock_meta.get(vt_symbol) or {}
            base_bars = _visible_bars_for_date(
                bars_by_symbol.get(vt_symbol, []),
                bar_dates_by_symbol.get(vt_symbol, []),
                base_daily_date,
            )
            if not base_bars:
                continue
            temp_bar = intraday_bars.get(vt_symbol) or _snapshot_temp_bar(stock, as_of, base_bars[-1])
            if temp_bar is None:
                continue
            if vt_symbol in intraday_bars:
                intraday_bar_count += 1
            else:
                snapshot_price_count += 1
            bars = [*base_bars, temp_bar]
            score = score_strategy(
                strategy.id,
                vt_symbol,
                bars,
                as_of,
                index_return_20d=index_return_20d,
                sector_score=sector_scores.get(vt_symbol),
                financial_score=financial_scores.get(vt_symbol),
                fund_flow_score=fund_flow_scores.get(vt_symbol),
                hot_rank_score=hot_rank_scores.get(vt_symbol),
                lhb_score=lhb_scores.get(vt_symbol),
            )
            if score.evidence.get("status") == "ready":
                score.evidence["close_price"] = float(temp_bar.close_price)
                _attach_market_context(score, market_payload)
                score.evidence["data_source"] = TAIL_PREVIEW_DATA_SOURCE
                score.evidence["temporary_bar"] = True
                score.evidence["base_daily_date"] = base_daily_date.isoformat()
                score.evidence["snapshot_updated_at"] = _iso_or_none(snapshot_updated_at)
                score.evidence["snapshot_trade_time"] = str(snapshot_trade_time) if snapshot_trade_time else None
                score.evidence["bar_mode"] = "minute_aggregate" if vt_symbol in intraday_bars else "snapshot_last_price"
                scored.append(score)

        scored.sort(key=lambda item: (-item.total_score, item.vt_symbol))
        recommendations = [
            item
            for item in scored
            if item.entry_signal or item.total_score >= min_recommendation_score
        ]
        recommendations = _select_recommendations(
            recommendations,
            strategy.id,
            strategy.default_min_entry_score,
            recommendation_limit,
        )

    return {
        "status": "ready" if scored else "empty",
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "trade_date": as_of.isoformat(),
        "run_id": None,
        "preview_mode": "tail_intraday",
        "data_source": TAIL_PREVIEW_DATA_SOURCE,
        "temporary_bar": True,
        "base_daily_date": base_daily_date.isoformat(),
        "latest_daily_date": latest_daily_date.isoformat() if latest_daily_date else None,
        "trade_date_daily_symbol_count": as_of_daily_symbol_count,
        "min_complete_daily_symbol_count": MIN_COMPLETE_DAILY_SYMBOL_COUNT,
        "snapshot_updated_at": _iso_or_none(snapshot_updated_at),
        "snapshot_trade_time": str(snapshot_trade_time) if snapshot_trade_time else None,
        "latest_intraday_date": latest_intraday_date.isoformat() if latest_intraday_date else None,
        "snapshot_price_count": snapshot_price_count,
        "intraday_bar_count": intraday_bar_count,
        "items": [
            _score_to_api(item, stock_meta.get(item.vt_symbol))
            for item in scored[: min(max(recommendation_limit, 1), 200)]
        ],
        "recommendations": [
            _recommendation_to_api(index + 1, item, stock_meta.get(item.vt_symbol))
            for index, item in enumerate(recommendations)
        ],
        "total": len(scored),
        "recommendation_count": len(recommendations),
        "included_boards": list(boards),
        "persistence": "read_only_not_persisted",
        "message": "今日尾盘预览使用盘中快照临时K线，不写入历史候选，不参与回测收益统计。",
    }


def get_tail_preview(
    trade_date: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    recommendation_limit: int = 100,
    min_recommendation_score: float = 60.0,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return today's tail preview, preferring the internal cache."""

    target_trade_date = trade_date or _tail_preview_default_trade_date()
    if target_trade_date is not None and not refresh:
        cached = latest_tail_preview_cache(target_trade_date, strategy_id=strategy_id)
        if cached is not None and _tail_preview_payload_has_intraday(cached):
            return _limit_tail_preview_payload(cached, recommendation_limit)
    return screen_tail_preview(
        target_trade_date,
        strategy_id=strategy_id,
        max_symbols=max_symbols,
        recommendation_limit=recommendation_limit,
        min_recommendation_score=min_recommendation_score,
        included_boards=included_boards,
    )


def generate_tail_preview_cache(
    trade_date: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    recommendation_limit: int = 100,
    min_recommendation_score: float = 60.0,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
    source_schedule_id: str | None = None,
) -> dict[str, Any]:
    """Compute and persist the current tail preview without touching historical signals."""

    payload = screen_tail_preview(
        trade_date,
        strategy_id=strategy_id,
        max_symbols=max_symbols,
        recommendation_limit=recommendation_limit,
        min_recommendation_score=min_recommendation_score,
        included_boards=included_boards,
    )
    if not is_database_configured():
        return payload
    if payload.get("status") != "ready" or not _tail_preview_payload_has_intraday(payload):
        return payload
    _ensure_quant_schema()

    payload = dict(payload)
    payload["cache"] = {
        "status": "generated",
        "source_schedule_id": source_schedule_id,
        "generated_at": datetime.now().isoformat(),
        "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
    }

    cache_trade_date = _parse_date(payload.get("trade_date")) or trade_date
    if cache_trade_date is None:
        return payload
    strategy = get_strategy(strategy_id)
    strategy_version = str(payload.get("strategy_version") or (strategy.version if strategy else STRATEGY_VERSION))
    now = datetime.now(timezone.utc)
    values = {
        "trade_date": cache_trade_date,
        "strategy_id": str(payload.get("strategy_id") or strategy_id),
        "strategy_version": strategy_version,
        "status": str(payload.get("status") or "empty"),
        "payload": payload,
        "source_schedule_id": source_schedule_id,
        "base_daily_date": _parse_date(payload.get("base_daily_date")),
        "latest_daily_date": _parse_date(payload.get("latest_daily_date")),
        "recommendation_count": int(payload.get("recommendation_count") or 0),
        "total": int(payload.get("total") or 0),
        "generated_at": now,
        "updated_at": now,
    }
    with session_scope() as session:
        stmt = pg_insert(schema.quant_tail_preview_cache).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                schema.quant_tail_preview_cache.c.trade_date,
                schema.quant_tail_preview_cache.c.strategy_id,
                schema.quant_tail_preview_cache.c.strategy_version,
            ],
            set_={
                "status": stmt.excluded.status,
                "payload": stmt.excluded.payload,
                "source_schedule_id": stmt.excluded.source_schedule_id,
                "base_daily_date": stmt.excluded.base_daily_date,
                "latest_daily_date": stmt.excluded.latest_daily_date,
                "recommendation_count": stmt.excluded.recommendation_count,
                "total": stmt.excluded.total,
                "generated_at": stmt.excluded.generated_at,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)
    payload["cache"]["status"] = "cached"
    return payload


def latest_tail_preview_cache(
    trade_date: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
) -> dict[str, Any] | None:
    """Load the latest cached tail preview payload for the strategy."""

    if not is_database_configured():
        return None
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return None
    _ensure_quant_schema()
    with session_scope() as session:
        query = select(schema.quant_tail_preview_cache).where(
            and_(
                schema.quant_tail_preview_cache.c.strategy_id == strategy.id,
                schema.quant_tail_preview_cache.c.strategy_version == strategy.version,
            )
        )
        if trade_date is not None:
            query = query.where(schema.quant_tail_preview_cache.c.trade_date == trade_date)
        row = session.execute(
            query.order_by(
                desc(schema.quant_tail_preview_cache.c.trade_date),
                desc(schema.quant_tail_preview_cache.c.generated_at),
                desc(schema.quant_tail_preview_cache.c.id),
            ).limit(1)
        ).mappings().first()
    if not row:
        return None
    payload = dict(row.get("payload") or {})
    cache = dict(payload.get("cache") or {})
    if cache.get("signal_evidence_schema_version") != screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION:
        return None
    if not _tail_preview_payload_has_intraday(payload):
        return None
    cache.update(
        {
            "status": "cached",
            "generated_at": _iso_or_none(row.get("generated_at")),
            "source_schedule_id": row.get("source_schedule_id"),
            "cache_id": int(row["id"]),
        }
    )
    payload["cache"] = cache
    return payload


def _tail_preview_default_trade_date() -> date | None:
    if not is_database_configured():
        return None
    _ensure_quant_schema()
    with session_scope() as session:
        base_daily_date = _latest_complete_trade_date(session) or _latest_trade_date(session)
        return _latest_tail_intraday_trade_date(session, base_daily_date)


def _limit_tail_preview_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    capped = min(max(int(limit or 100), 1), 200)
    result = dict(payload)
    if isinstance(result.get("items"), list):
        result["items"] = list(result["items"][:capped])
    if isinstance(result.get("recommendations"), list):
        result["recommendations"] = list(result["recommendations"][:capped])
    return result


def screen_stocks_range(
    start: date | None = None,
    end: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    min_recommendation_score: float = 60.0,
    persist: bool = False,
    auto_portfolio: bool = True,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
    force_refresh: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run daily screens for every local trading date in a range."""

    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": [], "recommendations": [], "runs": []}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": [], "recommendations": [], "runs": []}
    _ensure_quant_schema()
    boards = list(normalize_included_boards(included_boards))

    with session_scope() as session:
        latest = end or _latest_trade_date(session)
        if latest is None:
            return {"status": "empty", "message": "stock_daily_bars is empty", "items": [], "recommendations": [], "runs": []}
        start_date = start or _earliest_trade_date(session) or latest
        if start_date > latest:
            return {
                "status": "invalid_range",
                "message": "start date must be earlier than or equal to end date",
                "start_date": start_date.isoformat(),
                "end_date": latest.isoformat(),
                "items": [],
                "recommendations": [],
                "runs": [],
            }
        trade_dates = _trading_dates_between(session, start_date, latest)
        existing_runs = _screen_runs_by_date(session, strategy.id, strategy.version, trade_dates, max_symbols=max_symbols, included_boards=tuple(boards))

    if not trade_dates:
        return {
            "status": "empty",
            "message": "no local trading dates in range",
            "start_date": start_date.isoformat(),
            "end_date": latest.isoformat(),
            "items": [],
            "recommendations": [],
            "runs": [],
        }

    runs = []
    latest_result: dict[str, Any] | None = None
    succeeded_count = 0
    processed_count = 0
    range_recommendation_count = 0
    force_refreshed_count = 0
    range_context = _build_screen_range_context(start_date, latest, max_symbols, tuple(boards)) if _should_use_fast_range_context() else None

    processing_dates = list(reversed(trade_dates))
    latest_trade_date = trade_dates[-1]
    run_rows_by_date: dict[date, dict[str, Any]] = {}
    for index, trade_date in enumerate(processing_dates):
        existing_run = existing_runs.get(trade_date) if persist else None
        use_existing = bool(existing_run and not force_refresh)
        if existing_run and force_refresh:
            force_refreshed_count += 1
        if use_existing:
            result = _screen_result_from_existing_run(existing_run, strategy.id, strategy.version, boards)
            if auto_portfolio and trade_date == latest_trade_date:
                _sync_existing_recommendations_to_portfolio(existing_run["id"], strategy.id, strategy.version)
        else:
            result = screen_stocks(
                trade_date,
                strategy_id=strategy.id,
                max_symbols=max_symbols,
                recommendation_limit=recommendation_limit,
                min_recommendation_score=min_recommendation_score,
                persist=persist,
                auto_portfolio=auto_portfolio and trade_date == latest_trade_date,
                included_boards=boards,
                ensure_schema=False,
                range_context=range_context,
            )
        if trade_date == latest_trade_date:
            latest_result = result
        status = str(result.get("status") or "empty")
        if status == "ready":
            succeeded_count += 1
        if status in {"ready", "empty"}:
            processed_count += 1
        recommendation_count = int(result.get("recommendation_count") or 0)
        range_recommendation_count += recommendation_count
        run_rows_by_date[trade_date] = {
            "trade_date": trade_date.isoformat(),
            "status": status,
            "run_id": result.get("run_id"),
            "candidate_count": int(result.get("total") or 0),
            "recommendation_count": recommendation_count,
            "skipped_existing": use_existing,
            "force_refreshed": bool(existing_run and force_refresh),
        }
        if progress:
            progress(
                {
                    "trade_date": trade_date.isoformat(),
                    "progress_current": index + 1,
                    "progress_total": len(trade_dates),
                    "status": status,
                    "run_id": result.get("run_id"),
                    "skipped_existing": use_existing,
                    "force_refreshed": bool(existing_run and force_refresh),
                }
            )
    runs = [run_rows_by_date[trade_date] for trade_date in trade_dates if trade_date in run_rows_by_date]

    replay_run = None
    if persist:
        from alphaagent.server.services.quant import strategy_replay

        if progress:
            progress(
                {
                    "stage": "replay",
                    "message": "候选已补齐，正在生成买卖记录",
                    "progress_current": len(trade_dates),
                    "progress_total": len(trade_dates),
                    "status": "ready" if succeeded_count else str(latest_result.get("status") or "empty"),
                }
            )
        try:
            replay_run = strategy_replay.create_replay_run(
                start=trade_dates[0],
                end=trade_dates[-1],
                strategy_id=strategy.id,
                max_symbols=max_symbols,
                min_entry_score=float(getattr(strategy, "default_min_entry_score", min_recommendation_score) or min_recommendation_score),
                strict_entry=True,
                execution_model="legacy_next_open",
                included_boards=boards,
            )
        except Exception as exc:
            replay_run = {"status": "failed", "message": str(exc)}

    latest_result = latest_result or {}
    status = "ready" if succeeded_count else str(latest_result.get("status") or "empty")
    return {
        "status": status,
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "start_date": trade_dates[0].isoformat(),
        "end_date": trade_dates[-1].isoformat(),
        "trade_date": latest_result.get("trade_date") or trade_dates[-1].isoformat(),
        "run_id": latest_result.get("run_id"),
        "total_dates": len(trade_dates),
        "succeeded_count": succeeded_count,
        "processed_count": processed_count,
        "generated_count": sum(1 for item in runs if not item.get("skipped_existing")),
        "skipped_existing_count": sum(1 for item in runs if item.get("skipped_existing")),
        "force_refreshed_count": force_refreshed_count,
        "force_refresh": bool(force_refresh),
        "range_recommendation_count": range_recommendation_count,
        "total": int(latest_result.get("total") or 0),
        "recommendation_count": int(latest_result.get("recommendation_count") or 0),
        "included_boards": latest_result.get("included_boards") or boards,
        "replay_run": replay_run,
        "replay_run_id": replay_run.get("replay_run_id") if isinstance(replay_run, dict) else None,
        "items": latest_result.get("items") or [],
        "recommendations": latest_result.get("recommendations") or [],
        "portfolio_sync": latest_result.get("portfolio_sync"),
        "runs": runs,
    }


def list_signals(trade_date: date | None = None, strategy_id: str = STRATEGY_ID, limit: int = 100) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        run = _latest_screen_run(session, strategy.id, trade_date)
        if not run:
            as_of = trade_date or _latest_trade_date(session)
            return {
                "status": "empty",
                "trade_date": as_of.isoformat() if as_of else None,
                "run_id": None,
                "strategy_id": strategy.id,
                "strategy_version": strategy.version,
                "included_boards": list(DEFAULT_QUANT_INCLUDED_BOARDS),
                "items": [],
                "message": "当前信号证据版本没有候选缓存，请刷新候选。",
            }
        as_of = run["trade_date"]
        if as_of is None:
            return {"status": "empty", "items": []}
        rows = session.execute(
            select(schema.quant_stock_signals)
            .where(schema.quant_stock_signals.c.run_id == run["id"])
            .order_by(desc(schema.quant_stock_signals.c.total_score))
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
    return {
        "status": "ready" if rows else "empty",
        "trade_date": as_of.isoformat(),
        "run_id": int(run["id"]) if run else None,
        "strategy_id": strategy.id,
        "strategy_version": str(run["strategy_version"]) if run else strategy.version,
        "included_boards": _run_included_boards(run),
        "items": [_mapping_to_api(dict(row)) for row in rows],
    }


def list_screen_runs(strategy_id: str = STRATEGY_ID, limit: int = 120) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.quant_signal_runs)
            .where(
                and_(
                    schema.quant_signal_runs.c.strategy_id == strategy.id,
                    schema.quant_signal_runs.c.strategy_version == strategy.version,
                )
            )
            .order_by(desc(schema.quant_signal_runs.c.trade_date), desc(schema.quant_signal_runs.c.id))
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
        row_dicts = [dict(row) for row in rows]
        run_ids = [int(row["id"]) for row in row_dicts]
        action_counts: dict[int, dict[str, int]] = {run_id: {"BUY": 0, "WATCH": 0} for run_id in run_ids}
        if run_ids:
            count_rows = session.execute(
                select(
                    schema.quant_recommendations.c.run_id,
                    schema.quant_recommendations.c.action,
                    func.count().label("count"),
                )
                .where(schema.quant_recommendations.c.run_id.in_(run_ids))
                .group_by(schema.quant_recommendations.c.run_id, schema.quant_recommendations.c.action)
            ).mappings().all()
            for count_row in count_rows:
                run_id = int(count_row["run_id"])
                action = str(count_row["action"] or "").upper()
                if action in {"BUY", "WATCH"}:
                    action_counts.setdefault(run_id, {"BUY": 0, "WATCH": 0})[action] = int(count_row["count"] or 0)
        items = []
        for row in row_dicts:
            payload = _mapping_to_api(row)
            counts = action_counts.get(int(row["id"]), {"BUY": 0, "WATCH": 0})
            payload["buy_recommendation_count"] = counts["BUY"]
            payload["watch_recommendation_count"] = counts["WATCH"]
            items.append(payload)
    return {"status": "ready" if rows else "empty", "items": items}


def list_trading_dates(start: date | None = None, end: date | None = None, limit: int = 600) -> dict[str, Any]:
    """List local A-share trading dates from daily bar storage."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()

    filters = []
    if start is not None:
        filters.append(schema.stock_daily_bars.c.trade_date >= start)
    if end is not None:
        filters.append(schema.stock_daily_bars.c.trade_date <= end)

    query = (
        select(
            schema.stock_daily_bars.c.trade_date,
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)).label("symbol_count"),
        )
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(min(max(limit, 1), 2000))
    )
    if filters:
        query = query.where(and_(*filters))

    with session_scope() as session:
        rows = session.execute(query).mappings().all()
        min_query = select(func.min(schema.stock_daily_bars.c.trade_date))
        max_query = select(func.max(schema.stock_daily_bars.c.trade_date))
        if filters:
            min_query = min_query.where(and_(*filters))
            max_query = max_query.where(and_(*filters))
        earliest = session.execute(min_query).scalar()
        latest = session.execute(max_query).scalar()

    items = [
        {
            "trade_date": row["trade_date"].isoformat(),
            "symbol_count": int(row["symbol_count"] or 0),
        }
        for row in rows
    ]
    return {
        "status": "ready" if items else "empty",
        "items": items,
        "latest_trade_date": latest.isoformat() if latest else (items[0]["trade_date"] if items else None),
        "earliest_trade_date": earliest.isoformat() if earliest else None,
        "returned_count": len(items),
    }


def list_recommendations(
    trade_date: date | None = None,
    strategy_id: str = STRATEGY_ID,
    limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        run = _latest_screen_run(session, strategy.id, trade_date)
        if not run:
            as_of = trade_date or _latest_trade_date(session)
            return {
                "status": "empty",
                "trade_date": as_of.isoformat() if as_of else None,
                "run_id": None,
                "strategy_id": strategy.id,
                "strategy_version": strategy.version,
                "included_boards": list(DEFAULT_QUANT_INCLUDED_BOARDS),
                "items": [],
                "message": "当前信号证据版本没有候选缓存，请刷新候选。",
            }
        as_of = run["trade_date"]
        if as_of is None:
            return {"status": "empty", "items": []}
        rows = session.execute(
            select(
                schema.quant_recommendations,
                schema.stocks.c.name.label("stock_name"),
            )
            .select_from(
                schema.quant_recommendations.outerjoin(
                    schema.stocks,
                    schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(schema.quant_recommendations.c.run_id == run["id"])
            .order_by(schema.quant_recommendations.c.rank)
            .limit(min(max(limit, 1), 200))
        ).mappings().all()
    return {
        "status": "ready" if rows else "empty",
        "trade_date": as_of.isoformat(),
        "run_id": int(run["id"]) if run else None,
        "strategy_id": strategy.id,
        "strategy_version": str(run["strategy_version"]) if run else strategy.version,
        "included_boards": _run_included_boards(run),
        "items": [_recommendation_row_to_api(dict(row)) for row in rows],
    }


def latest_trade_plan(vt_symbol: str, strategy_id: str = STRATEGY_ID) -> dict[str, Any]:
    """返回某股最近一次候选的买卖计划（risk_control.trade_plan）。

    候选筛选时已预算并存储买卖计划，单股详情直接读取，避免重跑回测。
    """
    symbol = str(vt_symbol or "").strip().upper()
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id}
    _ensure_quant_schema()
    with session_scope() as session:
        row = session.execute(
            select(
                schema.quant_recommendations,
                schema.stocks.c.name.label("stock_name"),
            )
            .select_from(
                schema.quant_recommendations.outerjoin(
                    schema.stocks,
                    schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(
                and_(
                    schema.quant_recommendations.c.vt_symbol == symbol,
                    schema.quant_recommendations.c.strategy_id == strategy.id,
                )
            )
            .order_by(desc(schema.quant_recommendations.c.trade_date))
            .limit(1)
        ).mappings().first()
    if not row:
        return {"status": "empty", "vt_symbol": symbol, "message": "该股未在候选列表中"}
    risk_control = row.get("risk_control") or {}
    trade_plan = risk_control.get("trade_plan") if isinstance(risk_control, dict) else None
    return {
        "status": "ready" if trade_plan else "no_plan",
        "vt_symbol": symbol,
        "name": row.get("stock_name"),
        "trade_date": row["trade_date"].isoformat() if row.get("trade_date") else None,
        "strategy_id": strategy.id,
        "rank": row.get("rank"),
        "action": row.get("action"),
        "total_score": row.get("total_score"),
        "trade_plan": trade_plan,
        "risk_control": risk_control,
    }


def get_recommendation(recommendation_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()
    with session_scope() as session:
        row = session.execute(
            select(
                schema.quant_recommendations,
                schema.stocks.c.name.label("stock_name"),
            )
            .select_from(
                schema.quant_recommendations.outerjoin(
                    schema.stocks,
                    schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(schema.quant_recommendations.c.id == recommendation_id)
        ).mappings().first()
    if not row:
        return {"status": "not_found", "id": recommendation_id}
    return {"status": "ready", "item": _recommendation_row_to_api(dict(row))}


def get_run(run_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()
    with session_scope() as session:
        row = session.execute(select(schema.quant_signal_runs).where(schema.quant_signal_runs.c.id == run_id)).mappings().first()
    if not row:
        return {"status": "not_found", "id": run_id}
    return {"status": "ready", "item": _mapping_to_api(dict(row))}


def symbol_signal_history(
    vt_symbol: str,
    *,
    strategy_id: str = STRATEGY_ID,
    start: date | None = None,
    end: date | None = None,
    min_entry_score: float = 68.0,
    limit: int = 200,
) -> dict[str, Any]:
    symbol = str(vt_symbol or "").strip().upper()
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": []}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        stock = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol == symbol)).mappings().first()
        if not stock:
            return {"status": "not_found", "vt_symbol": symbol, "items": []}
        latest = end or session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date)).where(schema.stock_daily_bars.c.vt_symbol == symbol)
        ).scalar()
        if latest is None:
            return {"status": "empty", "vt_symbol": symbol, "items": []}
        earliest = start or session.execute(
            select(func.min(schema.stock_daily_bars.c.trade_date)).where(schema.stock_daily_bars.c.vt_symbol == symbol)
        ).scalar()
        financial_coverage = financial_coverage_summary(session, symbol, latest)
        bars = _load_bars(session, [symbol], latest, lookback_days=max((latest - earliest).days + 120, 200)).get(symbol, [])
        trade_dates = [bar.trade_date for bar in bars if earliest <= bar.trade_date <= latest]
        market_contexts = market_context.compute_market_contexts(session, schema, trade_dates)
        effective_min_entry_score = (
            float(min_entry_score)
            if min_entry_score is not None and float(min_entry_score) != 68.0
            else float(strategy.default_min_entry_score)
        )
        rows = []
        for trade_date in trade_dates:
            market_snapshot = market_contexts.get(trade_date)
            market_payload = market_snapshot.to_dict() if market_snapshot else None
            index_return_20d = (
                _float_or_none((market_payload or {}).get("index_return_20d"))
                if market_payload
                else _load_index_return_20d(session, trade_date)
            )
            sector_score = _load_sector_scores(session, [symbol], trade_date).get(symbol)
            financial_score = _load_financial_scores(session, [symbol], trade_date).get(symbol)
            fund_flow_score = _load_fund_flow_scores(session, [symbol], trade_date).get(symbol)
            hot_rank_score = _load_hot_rank_scores(session, [symbol], trade_date).get(symbol)
            lhb_score = _load_lhb_scores(session, [symbol], trade_date).get(symbol)
            score = score_strategy(
                strategy.id,
                symbol,
                bars,
                trade_date,
                index_return_20d=index_return_20d,
                sector_score=sector_score,
                financial_score=financial_score,
                fund_flow_score=fund_flow_score,
                hot_rank_score=hot_rank_score,
                lhb_score=lhb_score,
            )
            if score.evidence.get("status") != "ready":
                continue
            _attach_market_context(score, market_payload)
            rows.append(_symbol_signal_row(score, effective_min_entry_score))

    trigger_rows = [row for row in rows if row.get("executable_entry_signal")]
    near_rows = sorted(rows, key=lambda row: _symbol_signal_fit_key(row, strategy.id))[:limit]
    recent_rows = sorted(rows, key=lambda row: row["trade_date"], reverse=True)[:limit]
    best_total = max(rows, key=lambda row: float(row["total_score"]), default=None)
    best_entry_fit = near_rows[0] if near_rows else None
    scored_date_count = len(rows)
    return {
        "status": "ready" if rows else "empty",
        "vt_symbol": symbol,
        "name": stock.get("name"),
        **stock_board_payload(symbol, stock.get("exchange")),
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "start_date": earliest.isoformat() if earliest else None,
        "end_date": latest.isoformat(),
        "scored_date_count": scored_date_count,
        "entry_signal_count": len(trigger_rows),
        "watch_count": max(scored_date_count - len(trigger_rows), 0),
        "entry_signals": trigger_rows[:limit],
        "best_total_score": best_total,
        "best_entry_fit": best_entry_fit,
        "near_misses": near_rows,
        "recent": recent_rows,
        "financial_coverage": financial_coverage,
        "rule": _strategy_rule_payload(strategy.id, effective_min_entry_score),
    }


def symbol_strategy_comparison(
    vt_symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    """Compare every registered strategy for one stock and date range."""

    strategies = list_available_strategies().get("items") or []
    items: list[dict[str, Any]] = []
    base_payload: dict[str, Any] | None = None
    for strategy in strategies:
        strategy_id = str(strategy.get("id") or "")
        history = symbol_signal_history(
            vt_symbol,
            strategy_id=strategy_id,
            start=start,
            end=end,
            min_entry_score=float(strategy.get("default_min_entry_score") or 68.0),
            limit=limit,
        )
        if history.get("status") not in {"ready", "empty"}:
            items.append(
                {
                    "strategy": strategy,
                    "status": history.get("status"),
                    "strategy_id": strategy_id,
                    "strategy_version": strategy.get("version"),
                    "message": history.get("message"),
                    "scored_date_count": 0,
                    "entry_signal_count": 0,
                    "watch_count": 0,
                    "best_entry_fit": None,
                    "best_total_score": None,
                    "entry_signals": [],
                    "recent": [],
                    "rule": {},
                }
            )
            continue
        if base_payload is None:
            base_payload = {
                "vt_symbol": history.get("vt_symbol"),
                "name": history.get("name"),
                "board": history.get("board"),
                "board_label": history.get("board_label"),
                "start_date": history.get("start_date"),
                "end_date": history.get("end_date"),
                "financial_coverage": history.get("financial_coverage"),
            }
        recent = history.get("recent") or []
        items.append(
            {
                "strategy": strategy,
                "status": history.get("status"),
                "strategy_id": history.get("strategy_id") or strategy_id,
                "strategy_version": history.get("strategy_version") or strategy.get("version"),
                "scored_date_count": int(history.get("scored_date_count") or 0),
                "entry_signal_count": int(history.get("entry_signal_count") or 0),
                "watch_count": int(history.get("watch_count") or 0),
                "best_entry_fit": history.get("best_entry_fit"),
                "best_total_score": history.get("best_total_score"),
                "entry_signals": history.get("entry_signals") or [],
                "recent": recent,
                "rule": history.get("rule") or {},
            }
        )

    if base_payload is None:
        first = items[0] if items else {}
        return {
            "status": first.get("status") or "empty",
            "vt_symbol": str(vt_symbol or "").strip().upper(),
            "items": items,
        }
    return {
        "status": "ready",
        **base_payload,
        "items": items,
    }


def _ensure_quant_schema() -> None:
    """Allow quant screening to run from service calls, not only API startup."""

    schema.ensure_schema_once(get_engine())


def _latest_trade_date(session) -> date | None:
    return screening_loaders.latest_trade_date(session)


def _latest_complete_trade_date(session) -> date | None:
    return screening_loaders.latest_complete_trade_date(session, MIN_COMPLETE_DAILY_SYMBOL_COUNT)


def _daily_symbol_count(session, trade_date: date | None) -> int:
    if trade_date is None:
        return 0
    return screening_loaders.daily_symbol_count(session, trade_date)


def _earliest_trade_date(session) -> date | None:
    return screening_loaders.earliest_trade_date(session)


def _latest_signal_date(session) -> date | None:
    return screening_loaders.latest_signal_date(session)


def _latest_recommendation_date(session) -> date | None:
    return screening_loaders.latest_recommendation_date(session)


def _latest_screen_run(session, strategy_id: str, trade_date: date | None = None) -> dict[str, Any] | None:
    strategy = get_strategy(strategy_id)
    strategy_version = strategy.version if strategy else STRATEGY_VERSION
    return screening_loaders.latest_screen_run(
        session,
        strategy_id,
        strategy_version,
        trade_date,
        signal_evidence_schema_version=screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
    )


def _screen_runs_by_date(
    session,
    strategy_id: str,
    strategy_version: str,
    trade_dates: list[date],
    *,
    max_symbols: int = 5000,
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS,
) -> dict[date, dict[str, Any]]:
    if not trade_dates:
        return {}
    rows = session.execute(
        select(schema.quant_signal_runs)
        .where(
            and_(
                schema.quant_signal_runs.c.strategy_id == strategy_id,
                schema.quant_signal_runs.c.strategy_version == strategy_version,
                schema.quant_signal_runs.c.status.in_(["succeeded", "empty"]),
                schema.quant_signal_runs.c.trade_date.in_(trade_dates),
            )
        )
        .order_by(schema.quant_signal_runs.c.trade_date, desc(schema.quant_signal_runs.c.id))
    ).mappings().all()
    result: dict[date, dict[str, Any]] = {}
    for row in rows:
        trade_date = row["trade_date"]
        if trade_date not in result:
            run = dict(row)
            if _screen_run_matches_params(run, max_symbols=max_symbols, included_boards=included_boards):
                result[trade_date] = run
    return result


def _screen_run_matches_params(run: dict[str, Any], *, max_symbols: int, included_boards: tuple[str, ...]) -> bool:
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    if int(params.get("max_symbols") or 0) != int(max_symbols):
        return False
    if params.get("signal_evidence_schema_version") != screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION:
        return False
    return tuple(normalize_included_boards(params.get("included_boards"))) == tuple(normalize_included_boards(included_boards))


def _screen_result_from_existing_run(
    run: dict[str, Any],
    strategy_id: str,
    strategy_version: str,
    boards: list[str],
) -> dict[str, Any]:
    return {
        "status": "ready" if str(run.get("status") or "") == "succeeded" else str(run.get("status") or "empty"),
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "trade_date": run["trade_date"].isoformat(),
        "run_id": int(run["id"]),
        "total": int(run.get("candidate_count") or 0),
        "recommendation_count": int(run.get("recommendation_count") or 0),
        "included_boards": _run_included_boards(run) or boards,
        "items": [],
        "recommendations": [],
    }


def _sync_existing_recommendations_to_portfolio(run_id: int, strategy_id: str, strategy_version: str) -> dict[str, Any] | None:
    with session_scope() as session:
        rows = session.execute(
            select(schema.quant_recommendations)
            .where(schema.quant_recommendations.c.run_id == run_id)
            .order_by(schema.quant_recommendations.c.rank)
        ).mappings().all()
        if not rows:
            return None
        stock_meta_rows = session.execute(
            select(schema.stocks).where(schema.stocks.c.vt_symbol.in_([row["vt_symbol"] for row in rows]))
        ).mappings().all()
        stock_meta = {str(row["vt_symbol"]): dict(row) for row in stock_meta_rows}
        recommendations = [_recommendation_row_to_score(dict(row)) for row in rows]
        return _sync_quant_candidate_group(session, recommendations, stock_meta, strategy_id, strategy_version)


def _recommendation_row_to_score(row: dict[str, Any]) -> SignalScore:
    reason = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    return SignalScore(
        vt_symbol=str(row["vt_symbol"]),
        trade_date=row["trade_date"],
        signal_type=str(row.get("strategy_id") or STRATEGY_ID),
        total_score=float(row.get("total_score") or 0),
        relative_strength_score=float(reason.get("strong_leg_score") or 0),
        washout_score=float(reason.get("pullback_structure_score") or 0),
        trend_quality_score=float(reason.get("reclaim_confirmation_score") or 0),
        sector_mainline_score=float(reason.get("smart_money_proxy_score") or 0),
        financial_improvement_score=float(reason.get("financial_score") or 0),
        liquidity_score=float(reason.get("liquidity_score") or 0),
        risk_score=float(reason.get("risk_score") or 0),
        entry_signal=str(row.get("action") or "").upper() == "BUY",
        risk_level=str(reason.get("risk_level") or "MEDIUM"),
        evidence=reason,
    )


def _trading_dates_between(session, start: date, end: date) -> list[date]:
    return screening_loaders.trading_dates_between(session, start, end)


def _should_use_fast_range_context() -> bool:
    if screen_stocks is not _SCREEN_STOCKS_IMPL:
        return False
    try:
        with session_scope() as session:
            return hasattr(session, "execute")
    except Exception:
        return False


def _build_screen_range_context(start: date, end: date, max_symbols: int, boards: tuple[str, ...]) -> _ScreenRangeContext:
    with session_scope() as session:
        stock_rows = _load_stock_universe(session, max_symbols, boards)
        symbols = [str(row["vt_symbol"]) for row in stock_rows]
        bars_by_symbol = _load_bars(session, symbols, end, lookback_days=max((end - start).days + 160, 200))
    return _ScreenRangeContext(
        stock_rows=stock_rows,
        stock_meta={str(row["vt_symbol"]): dict(row) for row in stock_rows},
        symbols=symbols,
        bars_by_symbol=bars_by_symbol,
        bar_dates_by_symbol=_bar_dates_by_symbol(bars_by_symbol),
    )


def _bar_dates_by_symbol(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, list[date]]:
    return {vt_symbol: [bar.trade_date for bar in bars] for vt_symbol, bars in bars_by_symbol.items()}


def _visible_bars_for_date(bars: list[Bar], bar_dates: list[date], trade_date: date) -> list[Bar]:
    if not bars or not bar_dates:
        return []
    end_index = bisect_right(bar_dates, trade_date)
    if end_index <= 0 or bars[end_index - 1].trade_date != trade_date:
        return []
    start_index = max(0, end_index - 180)
    return bars[start_index:end_index]


def _run_included_boards(run: dict[str, Any] | None) -> list[str]:
    return screening_loaders.run_included_boards(run)


def _load_bars(session, vt_symbols: list[str], trade_date: date, lookback_days: int) -> dict[str, list[Bar]]:
    return screening_loaders.load_bars(session, vt_symbols, trade_date, lookback_days)


def _load_intraday_temp_bars(session, vt_symbols: list[str], trade_date: date) -> dict[str, Bar]:
    return screening_loaders.load_intraday_temp_bars(session, vt_symbols, trade_date)


def _latest_snapshot_updated_at(session) -> Any:
    return session.execute(select(func.max(schema.stocks.c.updated_at))).scalar()


def _latest_snapshot_trade_time(session) -> Any:
    return session.execute(select(func.max(schema.stocks.c.trade_time))).scalar()


def _latest_tail_intraday_trade_date(session, base_daily_date: date | None) -> date | None:
    query = select(func.max(schema.stock_minute_bars.c.trade_date)).where(
        schema.stock_minute_bars.c.interval == "1m"
    )
    if base_daily_date is not None:
        query = query.where(schema.stock_minute_bars.c.trade_date > base_daily_date)
    return session.execute(query).scalar()


def _tail_intraday_date_available(session, trade_date: date) -> bool:
    count = session.execute(
        select(func.count()).where(
            and_(
                schema.stock_minute_bars.c.trade_date == trade_date,
                schema.stock_minute_bars.c.interval == "1m",
            )
        )
    ).scalar()
    return bool(count)


def _tail_preview_waiting_payload(
    strategy,
    *,
    base_daily_date: date | None,
    latest_daily_date: date | None,
    latest_intraday_date: date | None,
    snapshot_updated_at: Any,
    snapshot_trade_time: Any,
    message: str,
    trade_date: date | None = None,
) -> dict[str, Any]:
    return {
        "status": "waiting_for_intraday_data",
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "trade_date": trade_date.isoformat() if trade_date else None,
        "run_id": None,
        "preview_mode": "tail_intraday",
        "data_source": TAIL_PREVIEW_DATA_SOURCE,
        "temporary_bar": True,
        "base_daily_date": base_daily_date.isoformat() if base_daily_date else None,
        "latest_daily_date": latest_daily_date.isoformat() if latest_daily_date else None,
        "latest_intraday_date": latest_intraday_date.isoformat() if latest_intraday_date else None,
        "snapshot_updated_at": _iso_or_none(snapshot_updated_at),
        "snapshot_trade_time": str(snapshot_trade_time) if snapshot_trade_time else None,
        "snapshot_price_count": 0,
        "intraday_bar_count": 0,
        "items": [],
        "recommendations": [],
        "total": 0,
        "recommendation_count": 0,
        "persistence": "read_only_not_persisted",
        "message": message,
    }


def _tail_preview_payload_has_intraday(payload: dict[str, Any]) -> bool:
    if int(payload.get("intraday_bar_count") or 0) > 0:
        return True
    return bool(payload.get("latest_intraday_date"))


def _snapshot_temp_bar(stock: dict[str, Any], trade_date: date, previous_bar: Bar) -> Bar | None:
    close_price = _float_or_none(stock.get("last_price"))
    if close_price is None or close_price <= 0:
        return None
    previous_close = float(previous_bar.close_price)
    high_price = max(previous_close, close_price)
    low_price = min(previous_close, close_price)
    turnover = _float_or_none(stock.get("turnover"))
    volume = _float_or_none(stock.get("volume"))
    if volume is None and turnover is not None and close_price > 0:
        volume = turnover / close_price / 100
    change_pct = _float_or_none(stock.get("change_pct"))
    return Bar(
        trade_date=trade_date,
        open_price=previous_close,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
        turnover=turnover,
        change_pct=change_pct,
    )


def _date_from_datetime(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return _parse_date(value)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _load_stock_universe(session, max_symbols: int, included_boards: tuple[str, ...]) -> list[dict[str, Any]]:
    return screening_loaders.load_stock_universe(session, max_symbols, included_boards)


def _load_index_return_20d(session, trade_date: date) -> float | None:
    return screening_loaders.load_index_return_20d(session, trade_date)


def _load_sector_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_sector_scores(session, vt_symbols, trade_date)


def _load_financial_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_financial_scores(session, vt_symbols, trade_date, _parse_date)


def _load_fund_flow_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_fund_flow_scores(session, vt_symbols, trade_date, _float_or_none, _clamp)


def _load_hot_rank_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_hot_rank_scores(session, vt_symbols, trade_date, _float_or_none, _clamp)


def _load_lhb_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_lhb_scores(session, vt_symbols, trade_date, _float_or_none, _clamp)


def _attach_market_context(score: SignalScore, payload: dict[str, Any] | None) -> None:
    if not payload:
        return
    compact_keys = (
        "regime",
        "label",
        "market_score",
        "trend_score",
        "momentum_score",
        "breadth_score",
        "risk_score",
        "theme_state",
        "dominant_theme",
        "dominant_theme_id",
        "theme_strength",
        "fund_flow_state",
        "fund_flow_label",
        "fund_flow_score",
        "fund_flow_streak_days",
        "fund_flow_source",
        "main_net_inflow",
        "main_net_inflow_ratio",
        "fund_flow_worsening_days",
        "fund_flow_new_low",
        "fund_flow_recovery_from_streak_days",
        "market_warning_level",
        "market_warning_label",
        "recovery_state",
        "recovery_label",
        "index_return_5d",
        "index_return_20d",
        "drawdown_60d_pct",
        "source",
        "notes",
    )
    context = {key: payload.get(key) for key in compact_keys if key in payload}
    score.evidence["market_context"] = context
    score.evidence["market_context_summary"] = market_context.market_context_summary(payload)
    score.evidence["dynamic_market_regime"] = payload.get("regime")
    score.evidence["dynamic_market_label"] = payload.get("label")
    score.evidence["market_warning_level"] = payload.get("market_warning_level")
    score.evidence["market_warning_label"] = payload.get("market_warning_label")
    score.evidence["fund_flow_state"] = payload.get("fund_flow_state")
    score.evidence["fund_flow_label"] = payload.get("fund_flow_label")
    score.evidence["fund_flow_streak_days"] = payload.get("fund_flow_streak_days")
    score.evidence["fund_flow_source"] = payload.get("fund_flow_source")
    score.evidence["recovery_state"] = payload.get("recovery_state")
    score.evidence["recovery_label"] = payload.get("recovery_label")


def _persist_screen_run(
    session,
    trade_date: date,
    scored: list[SignalScore],
    recommendations: list[SignalScore],
    strategy_id: str,
    strategy_version: str | tuple[str, ...] = STRATEGY_VERSION,
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS,
    max_symbols: int = 5000,
) -> int:
    if isinstance(strategy_version, tuple):
        included_boards = strategy_version
        strategy_version = STRATEGY_VERSION
    return screening_persistence.persist_screen_run(
        session,
        trade_date,
        scored,
        recommendations,
        strategy_id,
        strategy_version,
        included_boards,
        max_symbols=max_symbols,
    )


def _clear_existing_screen_outputs(session, trade_date: date, strategy_id: str, strategy_version: str = STRATEGY_VERSION) -> None:
    screening_persistence.clear_existing_screen_outputs(session, trade_date, strategy_id, strategy_version)


def _sync_quant_candidate_group(
    session,
    recommendations: list[SignalScore],
    stock_meta: dict[str, dict[str, Any]],
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
) -> dict[str, Any]:
    return screening_persistence.sync_quant_candidate_group(
        session,
        recommendations,
        stock_meta,
        strategy_id,
        strategy_version,
    )


def _ensure_auto_group(session, name: str, group_type: str, description: str) -> int:
    return screening_persistence.ensure_auto_group(session, name, group_type, description)


def _score_to_db(item: SignalScore, run_id: int | None, strategy_id: str, strategy_version: str = STRATEGY_VERSION) -> dict[str, Any]:
    return screening_payloads.score_to_db(item, run_id, strategy_id, strategy_version)


def _recommendation_to_db(
    rank: int,
    item: SignalScore,
    run_id: int | None,
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
    *,
    min_entry_score: float | None = None,
) -> dict[str, Any]:
    return screening_payloads.recommendation_to_db(
        rank,
        item,
        run_id,
        strategy_id,
        strategy_version,
        min_entry_score=min_entry_score,
    )


def _symbol_signal_row(item: SignalScore, min_entry_score: float) -> dict[str, Any]:
    return screening_payloads.symbol_signal_row(item, min_entry_score)


def _symbol_signal_fit_key(row: dict[str, Any], strategy_id: str) -> tuple[int, float, float]:
    return screening_payloads.symbol_signal_fit_key(row, strategy_id)


def _strategy_rule_payload(strategy_id: str, min_entry_score: float) -> dict[str, Any]:
    return screening_payloads.strategy_rule_payload(strategy_id, min_entry_score)


def _failed_entry_rules(item: SignalScore, min_entry_score: float) -> list[str]:
    return screening_payloads.failed_entry_rules(item, min_entry_score)


def _recommendation_sort_key(item: SignalScore, min_entry_score: float) -> tuple[int, int, float, int, float, float, str]:
    evidence = item.evidence or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    convergence = _float_or_default(evidence.get("ma_convergence_pct"), 999.0)
    low_suction_score = _float_or_default(evidence.get("low_suction_buildup_score"), 0.0)
    state = str(evidence.get("dragon_state") or "")
    buy_action = _recommendation_buy_action(item, min_entry_score)
    low_suction_watch = (
        not buy_action
        and state == "LOW_SUCTION_BUILDUP"
        and low_suction_days >= 2
    )
    return (
        0 if buy_action else 1,
        0 if low_suction_watch else 1,
        -float(item.total_score or 0),
        -int(low_suction_days),
        convergence,
        -low_suction_score,
        item.vt_symbol,
    )


def _select_recommendations(
    recommendations: list[SignalScore],
    strategy_id: str,
    min_entry_score: float,
    limit: int,
) -> list[SignalScore]:
    ordered = sorted(recommendations, key=lambda item: _recommendation_sort_key(item, min_entry_score))
    if strategy_id != DRAGON_PULLBACK_STRATEGY_ID:
        return ordered[:limit]
    buy_items = [item for item in ordered if _recommendation_buy_action(item, min_entry_score)]
    watch_items = [item for item in ordered if not _recommendation_buy_action(item, min_entry_score)]
    selected = candidate_lanes.select_dragon_pullback_execution_pool(buy_items, limit, strategy_id)
    selected_symbols = {item.vt_symbol for item in selected}
    if len(selected) < limit:
        selected.extend(item for item in watch_items if item.vt_symbol not in selected_symbols)
    return selected[:limit]


def _recommendation_buy_action(item: SignalScore, min_entry_score: float) -> bool:
    return bool(item.entry_signal and not screening_payloads.failed_entry_rules(item, min_entry_score))


def _float_or_default(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_to_api(item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    return screening_payloads.score_to_api(item, stock)


def _recommendation_to_api(rank: int, item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    return screening_payloads.recommendation_to_api(rank, item, stock)


def default_risk_control() -> dict[str, Any]:
    return screening_payloads.default_risk_control()


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.mapping_to_api(row)


def _recommendation_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.recommendation_row_to_api(row)


def _normalize_quant_evidence(value: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.normalize_quant_evidence(value)


def _normalize_risk_control(value: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.normalize_risk_control(value)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 4)
