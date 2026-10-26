from fastapi import APIRouter

from backend.app.api.routes import data_sources, health, system
from backend.app.api.routes import ibtracs, ml, typhoons


api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(data_sources.router)
api_router.include_router(ibtracs.router)
api_router.include_router(typhoons.router)
api_router.include_router(ml.router)

