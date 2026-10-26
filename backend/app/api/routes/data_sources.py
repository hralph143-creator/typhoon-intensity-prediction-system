from fastapi import APIRouter

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.system import DataSourceStatus
from backend.app.services.data_source_service import get_data_source_statuses


router = APIRouter(prefix="/data-sources", tags=["数据源"])


@router.get("/status", response_model=ApiResponse[list[DataSourceStatus]], summary="数据源接入状态")
def data_source_status() -> ApiResponse[list[DataSourceStatus]]:
    return ApiResponse(data=get_data_source_statuses())

