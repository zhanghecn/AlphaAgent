"""Root API router."""

from fastapi import APIRouter

from alphaagent.server.api.data_status import router as data_status_router
from alphaagent.server.api.data_sources import router as data_sources_router
from alphaagent.server.api.data_sync import router as data_sync_router
from alphaagent.server.api.backtests import router as backtests_router
from alphaagent.server.api.health import router as health_router
from alphaagent.server.api.system import router as system_router
from alphaagent.server.api.indices import router as indices_router
from alphaagent.server.api.industry_chains import router as industry_chains_router
from alphaagent.server.api.market import router as market_router
from alphaagent.server.api.portfolios import router as portfolios_router
from alphaagent.server.api.quant import router as quant_router
from alphaagent.server.api.research_graphs import router as research_graphs_router
from alphaagent.server.api.research_sectors import router as research_sectors_router
from alphaagent.server.api.research_stocks import router as research_stocks_router
from alphaagent.server.api.sectors import router as sectors_router
from alphaagent.server.api.simulation import router as simulation_router
from alphaagent.server.api.stocks import router as stocks_router
from alphaagent.server.api.vnpy_status import router as vnpy_status_router
try:
    from alphaagent.server.api.vnpy_local_data import router as vnpy_local_data_router
except ImportError:
    vnpy_local_data_router = None

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(system_router)
api_router.include_router(data_status_router)
api_router.include_router(data_sources_router)
api_router.include_router(data_sync_router)
api_router.include_router(market_router)
api_router.include_router(stocks_router)
api_router.include_router(indices_router)
api_router.include_router(sectors_router)
api_router.include_router(industry_chains_router)
api_router.include_router(research_sectors_router)
api_router.include_router(research_stocks_router)
api_router.include_router(research_graphs_router)
api_router.include_router(quant_router)
api_router.include_router(backtests_router)
api_router.include_router(portfolios_router)
api_router.include_router(simulation_router)
api_router.include_router(vnpy_status_router)
if vnpy_local_data_router is not None:
    api_router.include_router(vnpy_local_data_router)
