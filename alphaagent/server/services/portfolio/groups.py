"""Portfolio groups and watchlist management."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, desc, select

from alphaagent.market.boards import stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.simulation.account import latest_bar_close
from alphaagent.server.services.quant.factors import evaluate_exit


DEFAULT_GROUPS = [
    ("自选观察", "manual_watch", False, "用户手动加入的观察股票"),
    ("量化候选", "quant_candidate", True, "每日量化筛选候选，不代表买入"),
    ("自动模拟持仓", "simulation_auto", True, "策略触发后进入的模拟持仓"),
    ("短线低吸", "pullback_entry", False, "回踩均线和尾盘低吸观察"),
    ("趋势跟踪", "trend_follow", False, "趋势持续但未到低吸点"),
    ("长期质量", "quality_long", False, "财报和现金流改善明显"),
    ("已卖出复盘", "sold_review", False, "已卖出后的复盘池"),
    ("黑名单", "blacklist", False, "用户或风控禁止"),
]


def ensure_default_groups() -> None:
    if not is_database_configured():
        return
    _ensure_portfolio_schema()
    with session_scope() as session:
        for name, group_type, auto_managed, description in DEFAULT_GROUPS:
            existing = session.execute(
                select(schema.portfolio_groups.c.id).where(schema.portfolio_groups.c.name == name)
            ).scalar_one_or_none()
            if existing:
                continue
            session.execute(
                schema.portfolio_groups.insert().values(
                    name=name,
                    group_type=group_type,
                    auto_managed=auto_managed,
                    description=description,
                    risk_profile="balanced",
                )
            )


def list_groups() -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_default_groups()
    with session_scope() as session:
        rows = session.execute(select(schema.portfolio_groups).order_by(schema.portfolio_groups.c.sort_order, schema.portfolio_groups.c.id)).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def create_group(payload: dict[str, Any]) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    name = str(payload.get("name") or "").strip()
    if not name:
        return {"status": "invalid", "message": "name is required"}
    with session_scope() as session:
        group_id = session.execute(
            schema.portfolio_groups.insert()
            .values(
                name=name,
                group_type=str(payload.get("group_type") or "manual"),
                description=payload.get("description"),
                auto_managed=bool(payload.get("auto_managed") or False),
                risk_profile=str(payload.get("risk_profile") or "balanced"),
            )
            .returning(schema.portfolio_groups.c.id)
        ).scalar_one()
    return {"status": "ready", "id": int(group_id)}


def reorder_groups(group_ids: list[int]) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    with session_scope() as session:
        for idx, gid in enumerate(group_ids):
            session.execute(
                schema.portfolio_groups.update()
                .where(schema.portfolio_groups.c.id == gid)
                .values(sort_order=idx)
            )
    return {"status": "ready", "reordered": len(group_ids)}


def update_group(group_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    values = {key: payload[key] for key in ("name", "description", "risk_profile") if key in payload}
    if "auto_managed" in payload:
        values["auto_managed"] = bool(payload["auto_managed"])
    if not values:
        return {"status": "ready", "id": group_id, "updated": 0}
    with session_scope() as session:
        result = session.execute(schema.portfolio_groups.update().where(schema.portfolio_groups.c.id == group_id).values(**values))
    return {"status": "ready", "id": group_id, "updated": result.rowcount}


def delete_group(group_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    with session_scope() as session:
        result = session.execute(schema.portfolio_groups.delete().where(schema.portfolio_groups.c.id == group_id))
    return {"status": "ready", "id": group_id, "deleted": result.rowcount}


def list_items(group_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_portfolio_schema()
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.portfolio_group_items,
                schema.stocks.c.name.label("stock_name"),
                schema.stocks.c.exchange.label("stock_exchange"),
            )
            .select_from(
                schema.portfolio_group_items.outerjoin(
                    schema.stocks,
                    schema.portfolio_group_items.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(schema.portfolio_group_items.c.group_id == group_id)
            .order_by(schema.portfolio_group_items.c.created_at.desc())
        ).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def add_item(group_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_portfolio_schema()
    vt_symbol = str(payload.get("vt_symbol") or "").strip()
    if not vt_symbol:
        return {"status": "invalid", "message": "vt_symbol is required"}
    values = {
        "group_id": group_id,
        "vt_symbol": vt_symbol,
        "name": payload.get("name"),
        "source": str(payload.get("source") or "manual"),
        "reason": payload.get("reason"),
        "strategy_id": payload.get("strategy_id"),
        "strategy_version": payload.get("strategy_version"),
        "expires_at": _parse_date(payload.get("expires_at")),
    }
    with session_scope() as session:
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
    return {"status": "ready", "group_id": group_id, "vt_symbol": vt_symbol}


def delete_item(group_id: int, vt_symbol: str) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable"}
    _ensure_portfolio_schema()
    with session_scope() as session:
        result = session.execute(
            schema.portfolio_group_items.delete().where(
                and_(
                    schema.portfolio_group_items.c.group_id == group_id,
                    schema.portfolio_group_items.c.vt_symbol == vt_symbol,
                )
            )
        )
    return {"status": "ready", "deleted": result.rowcount}


def _apply_live_price(item: dict[str, Any], session) -> None:
    """Refresh last_price and derived valuation with the latest daily-bar close.

    Positions store last_price from the fill at build time; without this the
    holdings endpoint would show stale prices. Refreshing in-place keeps P&L,
    market value and (downstream) exit advice consistent with the live close.
    """
    vt_symbol = str(item.get("vt_symbol") or "")
    if not vt_symbol:
        return
    live_price = latest_bar_close(session, vt_symbol)
    if live_price is None or live_price <= 0:
        return
    cost = item.get("cost_price")
    volume = item.get("volume")
    item["last_price"] = live_price
    if isinstance(volume, (int, float)) and volume:
        item["market_value"] = live_price * volume
        if isinstance(cost, (int, float)) and cost:
            item["floating_pnl"] = (live_price - cost) * volume
            item["floating_pnl_pct"] = (live_price / cost - 1) * 100


def _as_date(value: Any):
    """Coerce a stored created_at (datetime/str/date) into a date, or None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _attach_advice(item: dict[str, Any]) -> None:
    """Attach a realtime exit advice to a holding item.

    Reuses factors.evaluate_exit (the single exit-rule source shared with the
    backtest engine) over the position's stored absolute exit levels and the
    (live-refreshed) last_price. Sets advice to one of
    hold/stop_loss/take_profit/trailing_stop/time_stop; defaults to "hold"
    when price data is missing or no rule fires.
    """
    last_price = item.get("last_price")
    if not isinstance(last_price, (int, float)) or last_price <= 0:
        item["advice"] = "hold"
        return
    reason = evaluate_exit(
        last_price=float(last_price),
        stop_loss_price=item.get("stop_loss_price"),
        take_profit_price=item.get("take_profit_price"),
        trailing_stop_price=item.get("trailing_stop_price"),
        entry_date=_as_date(item.get("created_at")),
        current_day=date.today(),
    )
    item["advice"] = reason or "hold"


def holdings() -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_portfolio_schema()
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.simulation_positions,
                schema.simulation_accounts.c.name.label("account_name"),
                schema.stocks.c.name.label("stock_name"),
                schema.stocks.c.exchange.label("stock_exchange"),
            )
            .join(schema.simulation_accounts, schema.simulation_positions.c.account_id == schema.simulation_accounts.c.id)
            .outerjoin(schema.stocks, schema.simulation_positions.c.vt_symbol == schema.stocks.c.vt_symbol)
            .order_by(schema.simulation_positions.c.updated_at.desc())
        ).mappings().all()
        items = []
        for row in rows:
            item = dict(row)
            _apply_live_price(item, session)
            _attach_advice(item)
            item.update(_position_trade_summary(session, int(row["account_id"]), str(row["vt_symbol"])))
            items.append(_mapping_to_api(item))
    return {"status": "ready", "items": items}


def _position_trade_summary(session, account_id: int, vt_symbol: str) -> dict[str, Any]:
    latest_buy = session.execute(
        select(
            schema.simulation_trades,
            schema.simulation_orders.c.reason.label("order_reason"),
            schema.simulation_orders.c.recommendation_id.label("recommendation_id"),
        )
        .join(schema.simulation_orders, schema.simulation_trades.c.order_id == schema.simulation_orders.c.id, isouter=True)
        .where(
            and_(
                schema.simulation_trades.c.account_id == account_id,
                schema.simulation_trades.c.vt_symbol == vt_symbol,
                schema.simulation_trades.c.side == "BUY",
            )
        )
        .order_by(desc(schema.simulation_trades.c.trade_time), desc(schema.simulation_trades.c.id))
        .limit(1)
    ).mappings().first()
    latest_sell = session.execute(
        select(schema.simulation_trades)
        .where(
            and_(
                schema.simulation_trades.c.account_id == account_id,
                schema.simulation_trades.c.vt_symbol == vt_symbol,
                schema.simulation_trades.c.side == "SELL",
            )
        )
        .order_by(desc(schema.simulation_trades.c.trade_time), desc(schema.simulation_trades.c.id))
        .limit(1)
    ).mappings().first()

    result: dict[str, Any] = {}
    if latest_buy:
        result.update(
            {
                "last_buy_time": latest_buy["trade_time"],
                "last_buy_price": latest_buy["price"],
                "last_buy_volume": latest_buy["volume"],
                "last_buy_amount": latest_buy["amount"],
                "last_buy_reason": latest_buy.get("order_reason"),
                "recommendation_id": latest_buy.get("recommendation_id"),
            }
        )
    if latest_sell:
        result.update(
            {
                "last_sell_time": latest_sell["trade_time"],
                "last_sell_price": latest_sell["price"],
                "last_sell_volume": latest_sell["volume"],
                "last_sell_amount": latest_sell["amount"],
                "last_sell_pnl": latest_sell["pnl"],
            }
        )
    return result


def _ensure_portfolio_schema() -> None:
    """Allow portfolio services to run outside the API lifespan."""

    schema.ensure_schema_once(get_engine())


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    vt_symbol = result.get("vt_symbol")
    if vt_symbol:
        result["name"] = result.get("name") or result.pop("stock_name", None)
        result.update(stock_board_payload(vt_symbol, result.pop("stock_exchange", None)))
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result
