"""Independent API surface for low-suction swing research."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.low_suction.swing_research_service import (
    get_swing_research,
)
from alphaagent.server.services.low_suction.cross_regime_validation_service import (
    get_cross_regime_validation,
)
from alphaagent.server.services.low_suction.swing_strategy_service import (
    get_swing_strategy_overview,
)
from alphaagent.server.services.low_suction.historical_replay_service import (
    get_historical_replay_overview,
    get_historical_replay_trade,
    get_historical_replay_trades,
)
from alphaagent.server.services.low_suction.causal_leader_pullback_forward_repository import (
    list_causal_forward_ledger,
)


router = APIRouter(prefix="/reverse-wrap", tags=["reverse-wrap"])


@router.get("/forward-ledger", response_model=None)
def natural_forward_ledger(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    signal_eligible: bool | None = None,
    terminal: bool | None = None,
):
    """Read immutable natural candidates and later outcomes as one ledger."""

    try:
        return ok(
            list_causal_forward_ledger(
                page=page,
                page_size=page_size,
                signal_eligible=signal_eligible,
                terminal=terminal,
            )
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail("LOW_SUCTION_FORWARD_FILTER_INVALID", str(exc)),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_FORWARD_LEDGER_UNAVAILABLE",
                "低吸自然前向流水暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/history", response_model=None)
def historical_replay_overview():
    """Read replay lineage and evidence grade without launching a replay."""

    try:
        return ok(get_historical_replay_overview())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_HISTORY_UNAVAILABLE",
                "低吸历史逐笔账本暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/history/trades", response_model=None)
def historical_replay_trades(
    run_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    market_phase: str | None = None,
    outcome: str | None = None,
    vt_symbol: str | None = None,
    sector_id: str | None = None,
):
    """Read one filtered page from an already-materialized replay."""

    try:
        return ok(
            get_historical_replay_trades(
                run_id=run_id,
                page=page,
                page_size=page_size,
                market_phase=market_phase,
                outcome=outcome,
                vt_symbol=vt_symbol,
                sector_id=sector_id,
            )
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content=fail("LOW_SUCTION_HISTORY_FILTER_INVALID", str(exc)),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_HISTORY_UNAVAILABLE",
                "低吸历史逐笔账本暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/history/trades/{signal_id}", response_model=None)
def historical_replay_trade(signal_id: str, run_id: str):
    """Read one replay trade and its causal evidence."""

    try:
        trade = get_historical_replay_trade(run_id=run_id, signal_id=signal_id)
        if trade is None:
            return JSONResponse(
                status_code=404,
                content=fail("LOW_SUCTION_HISTORY_TRADE_NOT_FOUND", "低吸交易不存在"),
            )
        return ok(trade)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_HISTORY_UNAVAILABLE",
                "低吸历史逐笔账本暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/cross-regime-validation", response_model=None)
def cross_regime_validation():
    """Read retained natural-forward diagnostics without retired reports."""

    try:
        return ok(get_cross_regime_validation())
    except (OSError, ValueError) as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_CROSS_REGIME_UNAVAILABLE",
                "跨行情低吸验收暂时不可用",
                {"reason": str(exc)},
            ),
        )


@router.get("/strategy", response_model=None)
def swing_strategy():
    """Read the forward paper strategy without exposing order mutations."""

    try:
        return ok(get_swing_strategy_overview())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_STRATEGY_UNAVAILABLE",
                "低吸波段纸面策略暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/swing-research", response_model=None)
def swing_research():
    """Read the fail-closed status for retired swing research evidence."""

    try:
        return ok(get_swing_research())
    except (OSError, ValueError) as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_RESEARCH_UNAVAILABLE",
                "低吸波段研究状态暂时不可用",
                {"reason": str(exc)},
            ),
        )
