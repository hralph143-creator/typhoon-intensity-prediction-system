import platform
import sys

from fastapi import APIRouter

from backend.app.core.config import PROJECT_ROOT, settings
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.system import RuntimeInfo


router = APIRouter(prefix="/system", tags=["系统信息"])


@router.get("/info", response_model=ApiResponse[RuntimeInfo], summary="系统信息")
def system_info() -> ApiResponse[RuntimeInfo]:
    database_path = settings.database_path
    return ApiResponse(
        data=RuntimeInfo(
            software_name=settings.app_name,
            brand=settings.app_brand,
            version=settings.app_version,
            environment=settings.app_env,
            python_version=platform.python_version(),
            platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
            database_type="SQLite" if settings.database_url.startswith("sqlite") else "其他",
            database_path=str(database_path) if database_path else "由连接地址配置",
            data_root=str(PROJECT_ROOT / "data"),
        )
    )

