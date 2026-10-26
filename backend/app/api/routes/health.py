from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.system import HealthStatus


router = APIRouter(tags=["系统状态"])


@router.get("/health", response_model=ApiResponse[HealthStatus], summary="健康检查")
def health_check(db: Session = Depends(get_db)) -> ApiResponse[HealthStatus]:
    db.execute(text("SELECT 1"))
    return ApiResponse(
        data=HealthStatus(status="healthy", database="connected", timestamp=datetime.now(UTC))
    )

