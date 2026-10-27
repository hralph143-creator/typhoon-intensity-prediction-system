from fastapi import APIRouter, HTTPException

from backend.app.schemas.common import ApiResponse
from backend.app.services.cma_service import import_local_files, status


router = APIRouter(prefix="/cma", tags=["CMA 独立最佳路径数据"])


@router.get("/status")
def get_status():
    return ApiResponse(data=status())


@router.post("/import-local")
def import_local():
    try:
        return ApiResponse(data=import_local_files(), message="CMA 独立最佳路径数据导入完成")
    except (FileNotFoundError, UnicodeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
