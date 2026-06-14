"""Persistence helpers for quant screening runs and portfolio groups."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from json import dumps
from typing import Any

from sqlalchemy import and_, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS
from alphaagent.server.db import schema
from alphaagent.server.services.quant import screening_payloads
from alphaagent.server.services.quant.factors import STRATEGY_VERSION, SignalScore
from alphaagent.server.services.quant.strategy_registry import require_strategy


def persist_screen_run(
    session,
    trade_date: date,
    scored: list[SignalScore],
    recommendations: list[SignalScore],
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS,
) -> int:
    now = datetime.now(timezone.utc)
    run_id = session.execute(
        schema.quant_signal_runs.insert()
        .values(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            trade_date=trade_date,
            status="succeeded",
            params={"included_boards": list(included_boards)},
            candidate_count=len(scored),
            signal_count=sum(1 for item in scored if item.entry_signal),
            recommendation_count=len(recommendations),
            message="daily close observable signal; execution model selected by backtest",
            finished_at=now,
        )
        .returning(schema.quant_signal_runs.c.id)
    ).scalar_one()

    clear_existing_screen_outputs(session, trade_date, strategy_id, strategy_version)

    for item in scored:
        values = screening_payloads.score_to_db(item, run_id, strategy_id, strategy_version)
        session.execute(schema.quant_stock_signals.insert().values(**values))

    strategy = require_strategy(strategy_id)
    for rank, item in enumerate(recommendations, start=1):
        values = screening_payloads.recommendation_to_db(
            rank,
            item,
            run_id,
            strategy_id,
            strategy_version,
            min_entry_score=strategy.default_min_entry_score,
        )
        session.execute(schema.quant_recommendations.insert().values(**values))
    return int(run_id)


def clear_existing_screen_outputs(session, trade_date: date, strategy_id: str, strategy_version: str = STRATEGY_VERSION) -> None:
    match_current_run = and_(
        schema.quant_recommendations.c.trade_date == trade_date,
        schema.quant_recommendations.c.strategy_id == strategy_id,
        schema.quant_recommendations.c.strategy_version == strategy_version,
    )
    session.execute(schema.quant_recommendations.delete().where(match_current_run))
    session.execute(
        schema.quant_stock_signals.delete().where(
            and_(
                schema.quant_stock_signals.c.trade_date == trade_date,
                schema.quant_stock_signals.c.strategy_id == strategy_id,
                schema.quant_stock_signals.c.strategy_version == strategy_version,
            )
        )
    )


def sync_quant_candidate_group(
    session,
    recommendations: list[SignalScore],
    stock_meta: dict[str, dict[str, Any]],
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
) -> dict[str, Any]:
    group_id = ensure_auto_group(session, "量化候选", "quant_candidate", "每日量化筛选候选，不代表买入")
    session.execute(
        schema.portfolio_group_items.delete().where(
            and_(
                schema.portfolio_group_items.c.group_id == group_id,
                schema.portfolio_group_items.c.source == "quant",
                schema.portfolio_group_items.c.strategy_id == strategy_id,
            )
        )
    )

    inserted = 0
    for rank, item in enumerate(recommendations, start=1):
        stock = stock_meta.get(item.vt_symbol) or {}
        values = {
            "group_id": group_id,
            "vt_symbol": item.vt_symbol,
            "name": stock.get("name"),
            "source": "quant",
            "reason": dumps(
                {
                    "rank": rank,
                    "total_score": item.total_score,
                    "trade_date": item.trade_date.isoformat(),
                    "selection_rule": item.evidence.get("selection_rule"),
                    "entry_setup": item.evidence.get("entry_setup"),
                    "entry_signal": item.entry_signal,
                    "risk_level": item.risk_level,
                },
                ensure_ascii=False,
            ),
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "expires_at": item.trade_date + timedelta(days=7),
        }
        existing = session.execute(
            select(schema.portfolio_group_items.c.vt_symbol).where(
                and_(
                    schema.portfolio_group_items.c.group_id == group_id,
                    schema.portfolio_group_items.c.vt_symbol == item.vt_symbol,
                )
            )
        ).scalar_one_or_none()
        if existing:
            session.execute(
                schema.portfolio_group_items.update()
                .where(
                    and_(
                        schema.portfolio_group_items.c.group_id == group_id,
                        schema.portfolio_group_items.c.vt_symbol == item.vt_symbol,
                    )
                )
                .values(**values)
            )
        else:
            session.execute(schema.portfolio_group_items.insert().values(**values))
        inserted += 1

    return {"group_id": int(group_id), "group_type": "quant_candidate", "synced": inserted}


def ensure_auto_group(session, name: str, group_type: str, description: str) -> int:
    existing = session.execute(
        select(schema.portfolio_groups.c.id).where(schema.portfolio_groups.c.group_type == group_type)
    ).scalar_one_or_none()
    if existing:
        return int(existing)
    return int(
        session.execute(
            schema.portfolio_groups.insert()
            .values(
                name=name,
                group_type=group_type,
                auto_managed=True,
                description=description,
                risk_profile="balanced",
            )
            .returning(schema.portfolio_groups.c.id)
        ).scalar_one()
    )
