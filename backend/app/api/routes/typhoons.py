from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.models.typhoon import SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.schemas.common import ApiResponse
from backend.app.services.typhoon_queries import event_dict, model_dict, observation_query, source_file_dict, statistics

router = APIRouter(prefix="/typhoons", tags=["历史台风（UTC / CMA 2分钟风速）"])


def require_event(db, event_id):
    event = db.get(TyphoonEvent, event_id)
    if not event:
        raise HTTPException(404, "台风记录不存在")
    return event


@router.get("/statistics", summary="真实数据统计：MAIN事件数、全部保留观测数及缺测数")
def get_statistics(source: str = Query("ibtracs", pattern="^(ibtracs|cma)$"), db: Session = Depends(get_db)):
    return ApiResponse(data=statistics(db, source))


@router.get("", summary="分页检索历史台风；最大风速仅取 MAIN 轨迹 CMA 2分钟平均，m/s")
def list_typhoons(
    season: int | None = Query(None, ge=2014, le=2025),
    name: str | None = Query(None, max_length=100),
    sid: str | None = Query(None, max_length=32),
    source: str = Query("ibtracs", max_length=32),
    category: int | None = Query(None, ge=0, le=9),
    min_wind: float | None = Query(None, ge=0),
    max_wind: float | None = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: Literal["season", "name", "maximum_wind", "first_observation"] = "season",
    sort_order: Literal["asc", "desc"] = "desc",
    include_spurs: bool = False,
    db: Session = Depends(get_db),
):
    query = select(TyphoonEvent).where(TyphoonEvent.source == source)
    if not include_spurs:
        query = query.where(TyphoonEvent.id.in_(select(TyphoonObservation.typhoon_id).where(TyphoonObservation.track_type == "MAIN")))
    if season:
        query = query.where(TyphoonEvent.season == season)
    if name:
        query = query.where(TyphoonEvent.name.icontains(name, autoescape=True))
    if sid:
        query = query.where(TyphoonEvent.sid.icontains(sid, autoescape=True))
    if category is not None:
        query = query.where(TyphoonEvent.maximum_category == category)
    if min_wind is not None:
        query = query.where(TyphoonEvent.maximum_wind >= min_wind)
    if max_wind is not None:
        query = query.where(TyphoonEvent.maximum_wind <= max_wind)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    field = getattr(TyphoonEvent, sort_by)
    query = query.order_by(field.asc() if sort_order == "asc" else field.desc(), TyphoonEvent.sid).offset((page - 1) * page_size).limit(page_size)
    return ApiResponse(data={"items": [event_dict(item) for item in db.scalars(query)], "total": total, "page": page, "page_size": page_size})


@router.get("/{event_id}", summary="台风档案及原始文件溯源")
def detail(event_id: int, db: Session = Depends(get_db)):
    event = require_event(db, event_id)
    file_ids = select(TyphoonObservation.source_file_id).where(TyphoonObservation.typhoon_id == event_id).distinct()
    files = db.scalars(select(SourceFile).where(SourceFile.id.in_(file_ids)))
    return ApiResponse(data={**event_dict(event), "source_files": [source_file_dict(item) for item in files]})


@router.get("/{event_id}/track", summary="历史轨迹，UTC；最多10000点，所有轨迹类型可单独查看")
@router.get("/{event_id}/intensity", summary="强度曲线；机构分别保留，风速m/s、气压hPa，缺测为null")
def track(event_id: int, track_type: str = Query("MAIN", max_length=32), db: Session = Depends(get_db)):
    require_event(db, event_id)
    items = [model_dict(item, exclude=("raw_values", "row_hash")) for item in db.scalars(observation_query(event_id, track_type.upper(), deduplicate=True).limit(10001))]
    if len(items) > 10000:
        raise HTTPException(413, "轨迹超过10000点，请使用分页观测接口")
    return ApiResponse(data={"items": items, "total": len(items), "track_type": track_type.upper(), "conflict_policy": "同一时刻和轨迹类型按最后导入的记录展示，全部冲突版本保留在分页观测接口", "wind_standards": {"CMA": "2分钟", "USA": "1分钟", "TOKYO": "10分钟", "WMO": "由实际负责机构决定"}})


@router.get("/{event_id}/observations", summary="分页原始与规范化观测记录，含原始字段与质量标记")
def observations(event_id: int, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), track_type: str = Query("MAIN", max_length=32), db: Session = Depends(get_db)):
    require_event(db, event_id)
    query = observation_query(event_id, track_type.upper())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size))
    return ApiResponse(data={"items": [model_dict(item) for item in items], "total": total, "page": page, "page_size": page_size})
