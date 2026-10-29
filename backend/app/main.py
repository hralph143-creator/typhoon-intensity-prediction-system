import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.core.logging import configure_logging
from backend.app.db.database import init_db


configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from backend.app.services.ibtracs_jobs import recover_interrupted_jobs
    recover_interrupted_jobs()
    from backend.app.services.ml_training import recover_training_jobs
    recover_training_jobs()
    from backend.app.services.era5_service import recover_download_jobs, recover_public_batches
    recover_download_jobs(); recover_public_batches()
    from backend.app.services.report_service import recover_reports
    recover_reports()
    logger.info("数据库初始化完成，应用已启动")
    yield
    logger.info("应用已停止")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="云浪智析科研软件后端接口（第六阶段：科研分析与成果导出）",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.middleware("http")
async def upload_size_limit(request: Request, call_next):
    length = request.headers.get("content-length")
    if request.url.path in {"/api/ibtracs/import", "/api/era5/import"} and length and length.isdigit() and int(length) > settings.upload_max_bytes + 1024 * 1024:
        return JSONResponse(status_code=413, content={"success": False, "message": "上传文件过大", "error": {"code": "FILE_TOO_LARGE"}})
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "message": str(exc.detail), "error": {"code": f"HTTP_{exc.status_code}"}}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"success": False, "message": "请求参数校验失败", "error": {"code": "VALIDATION_ERROR", "details": exc.errors()}}, custom_encoder={ValueError: str}),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理的服务异常", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "服务器内部错误", "error": {"code": "INTERNAL_ERROR"}},
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}

