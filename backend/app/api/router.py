from fastapi import APIRouter

from backend.app.api.routes import data_sources, health, system


api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(data_sources.router)

