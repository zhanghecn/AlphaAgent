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
    max_symbols: int = 5000,
    persist_signal_details: bool = True,
) -> int:
    now = datetime.now(timezone.utc)
    strategy = require_strategy(strategy_id)
    scored_candidates = _dedupe_scores_by_symbol(scored)
    recommendation_candidates = _dedupe_scores_by_symbol(recommendations)
    run_id = session.execute(
        schema.quant_signal_runs.insert()
        .values(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            trade_date=trade_date,
            status="succeeded",
            params={
                "included_boards": list(included_boards),
                "max_symbols": int(max_symbols),
                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
            },
            candidate_count=len(scored_candidates),
            signal_count=sum(
                1
                for item in scored_candidates
                if screening_payloads.entry_action_payload(item, strategy.default_min_entry_score)["executable_entry_signal"]
            ),
            recommendation_count=len(recommendation_candidates),
            message="daily close observable signal; execution model selected by backtest",
            finished_at=now,
        )
        .returning(schema.quant_signal_runs.c.id)
    ).scalar_one()

    clear_existing_screen_outputs(session, trade_date, strategy_id, strategy_version)

    if persist_signal_details:
        signal_rows = [
            screening_payloads.score_to_db(item, run_id, strategy_id, strategy_version)
            for item in scored_candidates
        ]
        if signal_rows:
            session.execute(schema.quant_stock_signals.insert(), signal_rows)

    recommendation_rows = [
        screening_payloads.recommendation_to_db(
            rank,
            item,
            run_id,
            strategy_id,
            strategy_version,
            min_entry_score=strategy.default_min_entry_score,
        )
        for rank, item in enumerate(recommendation_candidates, start=1)
    ]
    if recommendation_rows:
        session.execute(schema.quant_recommendations.insert(), recommendation_rows)
    return int(run_id)


def _dedupe_scores_by_symbol(items: list[SignalScore]) -> list[SignalScore]:
    result: list[SignalScore] = []
    seen: set[str] = set()
    for item in items:
        if item.vt_symbol in seen:
            continue
        seen.add(item.vt_symbol)
        result.append(item)
    return result


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
    strategy = require_strategy(strategy_id)
    for rank, item in enumerate(recommendations, start=1):
        stock = stock_meta.get(item.vt_symbol) or {}
        action_payload = screening_payloads.entry_action_payload(item, strategy.default_min_entry_score)
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
                    "entry_signal": action_payload["executable_entry_signal"],
                    "raw_entry_signal": action_payload["raw_entry_signal"],
                    "executable_entry_signal": action_payload["executable_entry_signal"],
                    "action": action_payload["action"],
                    "signal_label": action_payload["signal_label"],
                    "signal_role": action_payload["signal_role"],
                    "key_entry_signal": action_payload["key_entry_signal"],
                    "failed_rules": action_payload["failed_rules"],
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
