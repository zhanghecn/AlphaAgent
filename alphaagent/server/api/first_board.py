"""Stateless realtime API for 潜龙首板."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.first_board.live_service import get_live_first_board


router = APIRouter(prefix="/first-board", tags=["first-board"])


@router.get("/live", response_model=None)
def live():
    try:
        return ok(get_live_first_board())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "FIRST_BOARD_LIVE_UNAVAILABLE",
                "潜龙首板实时行情暂时不可用，请稍后刷新。",
                {"reason": exc.__class__.__name__},
            ),
        )
