from fastapi import APIRouter

from backend.app.api.routes import data_sources, health, system
from backend.app.api.routes import cma, era5, exports, fusion, ibtracs, ml, reports, typhoons


api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(data_sources.router)
api_router.include_router(ibtracs.router)
api_router.include_router(cma.router)
api_router.include_router(typhoons.router)
api_router.include_router(ml.router)
api_router.include_router(era5.router)
api_router.include_router(fusion.router)
api_router.include_router(reports.router)
api_router.include_router(exports.router)

