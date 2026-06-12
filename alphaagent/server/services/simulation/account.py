"""Local simulation account service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, desc, select

from alphaagent.market.boards import stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.quant.factors import STRATEGY_VERSION


DEFAULT_COMMISSION_RATE = 0.0003
DEFAULT_STAMP_TAX_RATE = 0.0005


def list_accounts() -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_simulation_schema()
    with session_scope() as session:
        rows = session.execute(select(schema.simulation_accounts).order_by(schema.simulation_accounts.c.id)).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def create_account(payload: dict[str, Any]) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_simulation_schema()
    name = str(payload.get("name") or "模拟账户")
    initial_cash = float(payload.get("initial_cash") or 1_000_000)
    with session_scope() as session:
        account_id = session.execute(
            schema.simulation_accounts.insert()
            .values(name=name, initial_cash=initial_cash, cash=initial_cash, status="active")
            .returning(schema.simulation_accounts.c.id)
        ).scalar_one()
    return {"status": "ready", "id": int(account_id)}


def ensure_default_account(initial_cash: float = 1_000_000) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_simulation_schema()
    with session_scope() as session:
        existing = session.execute(
            select(schema.simulation_accounts)
            .where(schema.simulation_accounts.c.name == "量化模拟账户")
            .order_by(schema.simulation_accounts.c.id)
            .limit(1)
        ).mappings().first()
        if existing:
            return {"status": "ready", "id": int(existing["id"]), "created": False}
        account_id = session.execute(
            schema.simulation_accounts.insert()
            .values(name="量化模拟账户", initial_cash=initial_cash, cash=initial_cash, status="active")
            .returning(schema.simulation_accounts.c.id)
        ).scalar_one()
    return {"status": "ready", "id": int(account_id), "created": True}


def list_positions(account_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_simulation_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.simulation_positions)
            .where(schema.simulation_positions.c.account_id == account_id)
            .order_by(schema.simulation_positions.c.updated_at.desc())
        ).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def list_orders(account_id: int, limit: int = 100) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_simulation_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.simulation_orders)
            .where(schema.simulation_orders.c.account_id == account_id)
            .order_by(schema.simulation_orders.c.id.desc())
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def list_trades(account_id: int, limit: int = 100) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_simulation_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.simulation_trades)
            .where(schema.simulation_trades.c.account_id == account_id)
            .order_by(schema.simulation_trades.c.id.desc())
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def place_order(account_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_simulation_schema()
    vt_symbol = str(payload.get("vt_symbol") or "").strip()
    side = str(payload.get("side") or "BUY").upper()
    if not vt_symbol or side not in {"BUY", "SELL"}:
        return {"status": "invalid", "message": "vt_symbol and side BUY/SELL are required"}
    with session_scope() as session:
        account = session.execute(select(schema.simulation_accounts).where(schema.simulation_accounts.c.id == account_id)).mappings().first()
        if not account:
            return {"status": "not_found", "message": "account not found"}
        stock = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol == vt_symbol)).mappings().first()
        price = float(payload.get("price") or (stock.get("last_price") if stock else 0) or 0)
        if price <= 0:
            return {"status": "invalid", "message": "price is required when latest price is unavailable"}
        volume = _resolve_volume(payload, price)
        if volume <= 0:
            return {"status": "invalid", "message": "volume or amount is too small"}
        order_id = session.execute(
            schema.simulation_orders.insert()
            .values(
                account_id=account_id,
                vt_symbol=vt_symbol,
                side=side,
                price=price,
                volume=volume,
                amount=price * volume,
                status="submitted",
                reason=payload.get("reason"),
                recommendation_id=payload.get("recommendation_id"),
            )
            .returning(schema.simulation_orders.c.id)
        ).scalar_one()
        fill = _fill_order(session, dict(account), int(order_id), vt_symbol, side, price, volume, payload)
    return fill


def auto_buy_recommendations(account_id: int | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_simulation_schema()
    payload = payload or {}
    if account_id is None:
        account_info = ensure_default_account(float(payload.get("initial_cash") or 1_000_000))
        if account_info.get("status") != "ready":
            return account_info
        account_id = int(account_info["id"])

    limit = min(max(int(payload.get("limit") or 5), 1), 20)
    amount_per_order = float(payload.get("amount_per_order") or 100_000)
    strategy_id = str(payload.get("strategy_id") or "mainline_leader_pullback")

    fills: list[dict[str, Any]] = []
    synced_group_items = 0
    with session_scope() as session:
        recommendations = session.execute(
            select(schema.quant_recommendations)
            .where(
                and_(
                    schema.quant_recommendations.c.strategy_id == strategy_id,
                    schema.quant_recommendations.c.status == "active",
                    schema.quant_recommendations.c.action == "BUY",
                )
            )
            .order_by(desc(schema.quant_recommendations.c.trade_date), schema.quant_recommendations.c.rank)
            .limit(limit)
        ).mappings().all()
        if not recommendations:
            return {"status": "empty", "account_id": account_id, "items": [], "message": "no BUY recommendations"}

        account = session.execute(select(schema.simulation_accounts).where(schema.simulation_accounts.c.id == account_id)).mappings().first()
        if not account:
            return {"status": "not_found", "message": "account not found"}

        for recommendation in recommendations:
            vt_symbol = str(recommendation["vt_symbol"])
            position = session.execute(
                select(schema.simulation_positions).where(
                    and_(
                        schema.simulation_positions.c.account_id == account_id,
                        schema.simulation_positions.c.vt_symbol == vt_symbol,
                    )
                )
            ).mappings().first()
            if position:
                fills.append({"status": "skipped", "vt_symbol": vt_symbol, "reason": "already_position"})
                continue

            stock = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol == vt_symbol)).mappings().first()
            latest_bar = session.execute(
                select(schema.stock_daily_bars)
                .where(schema.stock_daily_bars.c.vt_symbol == vt_symbol)
                .order_by(desc(schema.stock_daily_bars.c.trade_date))
                .limit(1)
            ).mappings().first()
            price = float((latest_bar or {}).get("close_price") or (stock or {}).get("last_price") or 0)
            if price <= 0:
                fills.append({"status": "rejected", "vt_symbol": vt_symbol, "reason": "price_unavailable"})
                continue
            volume = int(amount_per_order / price / 100) * 100
            if volume <= 0:
                fills.append({"status": "rejected", "vt_symbol": vt_symbol, "reason": "amount_too_small"})
                continue

            order_id = session.execute(
                schema.simulation_orders.insert()
                .values(
                    account_id=account_id,
                    vt_symbol=vt_symbol,
                    side="BUY",
                    price=price,
                    volume=volume,
                    amount=price * volume,
                    status="submitted",
                    reason=f"quant recommendation #{recommendation['rank']}",
                    recommendation_id=recommendation["id"],
                )
                .returning(schema.simulation_orders.c.id)
            ).scalar_one()
            account = session.execute(select(schema.simulation_accounts).where(schema.simulation_accounts.c.id == account_id)).mappings().one()
            fill = _fill_order(
                session,
                dict(account),
                int(order_id),
                vt_symbol,
                "BUY",
                price,
                volume,
                {
                    "name": (stock or {}).get("name"),
                    "source": "quant_auto",
                    "reason": f"quant recommendation #{recommendation['rank']}",
                    "recommendation_id": recommendation["id"],
                },
            )
            fill["vt_symbol"] = vt_symbol
            if fill.get("status") == "filled":
                synced_group_items += _upsert_simulation_auto_group_item(
                    session,
                    vt_symbol,
                    (stock or {}).get("name"),
                    strategy_id,
                    f"quant recommendation #{recommendation['rank']}",
                    recommendation,
                    price,
                    volume,
                )
            fills.append(fill)

    filled = sum(1 for item in fills if item.get("status") == "filled")
    return {
        "status": "ready",
        "account_id": account_id,
        "filled": filled,
        "auto_position_sync": {
            "group_type": "simulation_auto",
            "synced": synced_group_items,
        },
        "items": fills,
    }


def list_risk_events(account_id: int, limit: int = 100) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_simulation_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.risk_events)
            .where(schema.risk_events.c.account_id == account_id)
            .order_by(schema.risk_events.c.id.desc())
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def _upsert_simulation_auto_group_item(
    session,
    vt_symbol: str,
    name: str | None,
    strategy_id: str,
    reason: str,
    recommendation: dict[str, Any],
    price: float,
    volume: int,
) -> int:
    group_id = _ensure_auto_group(session, "自动模拟持仓", "simulation_auto", "策略触发后进入的模拟持仓")
    values = {
        "group_id": group_id,
        "vt_symbol": vt_symbol,
        "name": name,
        "source": "simulation_auto",
        "reason": (
            f"{reason}; cost={price:.4f}; volume={volume}; "
            f"trade_date={recommendation['trade_date']}; score={recommendation.get('total_score')}"
        ),
        "strategy_id": strategy_id,
        "strategy_version": str(recommendation.get("strategy_version") or STRATEGY_VERSION),
        "expires_at": None,
    }
    existing = session.execute(
        select(schema.portfolio_group_items.c.vt_symbol).where(
            and_(
                schema.portfolio_group_items.c.group_id == group_id,
                schema.portfolio_group_items.c.vt_symbol == vt_symbol,
            )
        )
    ).scalar_one_or_none()
    if existing:
        session.execute(
            schema.portfolio_group_items.update()
            .where(
                and_(
                    schema.portfolio_group_items.c.group_id == group_id,
                    schema.portfolio_group_items.c.vt_symbol == vt_symbol,
                )
            )
            .values(**values)
        )
    else:
        session.execute(schema.portfolio_group_items.insert().values(**values))
    return 1


def _ensure_auto_group(session, name: str, group_type: str, description: str) -> int:
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


def _ensure_simulation_schema() -> None:
    """Allow simulation services to run outside the API lifespan."""

    schema.create_schema(get_engine())


def _fill_order(session, account: dict[str, Any], order_id: int, vt_symbol: str, side: str, price: float, volume: int, payload: dict[str, Any]) -> dict[str, Any]:
    amount = price * volume
    fee = amount * DEFAULT_COMMISSION_RATE
    if side == "SELL":
        fee += amount * DEFAULT_STAMP_TAX_RATE
    cash = float(account["cash"])
    position = session.execute(
        select(schema.simulation_positions).where(
            and_(
                schema.simulation_positions.c.account_id == account["id"],
                schema.simulation_positions.c.vt_symbol == vt_symbol,
            )
        )
    ).mappings().first()

    if side == "BUY":
        if cash < amount + fee:
            _reject_order(session, order_id, account["id"], vt_symbol, "insufficient_cash")
            return {"status": "rejected", "order_id": order_id, "reason": "insufficient_cash"}
        _apply_buy(session, account, position, vt_symbol, price, volume, amount, fee, payload)
        pnl = None
    else:
        if not position or int(position["available"]) < volume:
            _reject_order(session, order_id, account["id"], vt_symbol, "insufficient_position")
            return {"status": "rejected", "order_id": order_id, "reason": "insufficient_position"}
        pnl = _apply_sell(session, account, position, vt_symbol, price, volume, amount, fee)

    session.execute(schema.simulation_orders.update().where(schema.simulation_orders.c.id == order_id).values(status="filled"))
    trade_id = session.execute(
        schema.simulation_trades.insert()
        .values(
            account_id=account["id"],
            order_id=order_id,
            vt_symbol=vt_symbol,
            side=side,
            price=price,
            volume=volume,
            amount=amount,
            fee=fee,
            pnl=pnl,
            trade_time=datetime.now(timezone.utc),
        )
        .returning(schema.simulation_trades.c.id)
    ).scalar_one()
    return {"status": "filled", "order_id": order_id, "trade_id": int(trade_id)}


def _apply_buy(session, account: dict[str, Any], position, vt_symbol: str, price: float, volume: int, amount: float, fee: float, payload: dict[str, Any]) -> None:
    new_cash = float(account["cash"]) - amount - fee
    session.execute(schema.simulation_accounts.update().where(schema.simulation_accounts.c.id == account["id"]).values(cash=new_cash))
    if position:
        old_volume = int(position["volume"])
        new_volume = old_volume + volume
        new_cost = (float(position["cost_price"]) * old_volume + amount) / new_volume
        session.execute(
            schema.simulation_positions.update()
            .where(
                and_(
                    schema.simulation_positions.c.account_id == account["id"],
                    schema.simulation_positions.c.vt_symbol == vt_symbol,
                )
            )
            .values(
                volume=new_volume,
                available=new_volume,
                cost_price=new_cost,
                last_price=price,
                market_value=price * new_volume,
                floating_pnl=(price - new_cost) * new_volume,
                floating_pnl_pct=(price / new_cost - 1) * 100 if new_cost else 0,
            )
        )
    else:
        session.execute(
            schema.simulation_positions.insert().values(
                account_id=account["id"],
                vt_symbol=vt_symbol,
                name=payload.get("name"),
                volume=volume,
                available=volume,
                cost_price=price,
                last_price=price,
                market_value=price * volume,
                floating_pnl=0,
                floating_pnl_pct=0,
                stop_loss_price=price * 0.93,
                take_profit_price=price * 1.18,
                trailing_stop_price=price * 0.92,
                source=str(payload.get("source") or "manual"),
                reason=payload.get("reason"),
            )
        )


def _apply_sell(session, account: dict[str, Any], position, vt_symbol: str, price: float, volume: int, amount: float, fee: float) -> float:
    cost = float(position["cost_price"])
    pnl = (price - cost) * volume - fee
    new_cash = float(account["cash"]) + amount - fee
    session.execute(schema.simulation_accounts.update().where(schema.simulation_accounts.c.id == account["id"]).values(cash=new_cash))
    remaining = int(position["volume"]) - volume
    if remaining <= 0:
        session.execute(
            schema.simulation_positions.delete().where(
                and_(
                    schema.simulation_positions.c.account_id == account["id"],
                    schema.simulation_positions.c.vt_symbol == vt_symbol,
                )
            )
        )
    else:
        session.execute(
            schema.simulation_positions.update()
            .where(
                and_(
                    schema.simulation_positions.c.account_id == account["id"],
                    schema.simulation_positions.c.vt_symbol == vt_symbol,
                )
            )
            .values(
                volume=remaining,
                available=remaining,
                last_price=price,
                market_value=price * remaining,
                floating_pnl=(price - cost) * remaining,
                floating_pnl_pct=(price / cost - 1) * 100 if cost else 0,
            )
        )
    return pnl


def _reject_order(session, order_id: int, account_id: int, vt_symbol: str, reason: str) -> None:
    session.execute(schema.simulation_orders.update().where(schema.simulation_orders.c.id == order_id).values(status="rejected"))
    session.execute(
        schema.risk_events.insert().values(
            account_id=account_id,
            vt_symbol=vt_symbol,
            event_type="order_rejected",
            severity="medium",
            message=reason,
            context={"order_id": order_id},
        )
    )


def _resolve_volume(payload: dict[str, Any], price: float) -> int:
    if payload.get("volume") is not None:
        return int(payload["volume"]) // 100 * 100
    amount = float(payload.get("amount") or 0)
    return int(amount / price / 100) * 100


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    vt_symbol = result.get("vt_symbol")
    if vt_symbol:
        result.update(stock_board_payload(vt_symbol))
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result
