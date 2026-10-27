"""历史查询仅按同一机构口径汇总，返回有限大小结果。"""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.typhoon import ImportJob, SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.services.ibtracs_jobs import job_dict


def model_dict(record, *, exclude=()) -> dict:
    result = {}
    for column in record.__table__.columns:
        if column.name in exclude:
            continue
        value = getattr(record, column.name)
        if isinstance(value, datetime):
            value = value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
        result[column.name] = value
    return result


def source_file_dict(record) -> dict:
    result = model_dict(record)
    result["filename"] = result["original_filename"]
    result["size_bytes"] = result["file_size"]
    return result


def event_dict(event) -> dict:
    result = model_dict(event)
    result.update(wind_agency="CMA", wind_averaging_minutes=2, wind_unit="m/s", pressure_unit="hPa", summary_track_type="MAIN")
    return result


def statistics(db: Session, source: str = "ibtracs") -> dict:
    source_ids = select(TyphoonEvent.id).where(TyphoonEvent.source == source)
    main_ids = select(TyphoonObservation.typhoon_id).where(TyphoonObservation.track_type == "MAIN", TyphoonObservation.typhoon_id.in_(source_ids)).distinct()
    yearly = db.execute(select(TyphoonEvent.season, func.count()).where(TyphoonEvent.id.in_(main_ids)).group_by(TyphoonEvent.season).order_by(TyphoonEvent.season)).all()
    yearly_all = db.execute(select(TyphoonEvent.season, func.count()).where(TyphoonEvent.source == source).group_by(TyphoonEvent.season).order_by(TyphoonEvent.season)).all()
    latest = db.scalar(select(ImportJob).where(ImportJob.source == source).order_by(ImportJob.started_at.desc()).limit(1))
    last_import = db.scalar(select(func.max(SourceFile.imported_at)).where(SourceFile.status == "imported", SourceFile.source == source))
    return {
        "typhoon_count": sum(item[1] for item in yearly),
        "source": source,
        "all_event_count": db.scalar(select(func.count()).select_from(TyphoonEvent).where(TyphoonEvent.source == source)),
        "observation_count": db.scalar(select(func.count()).select_from(TyphoonObservation).where(TyphoonObservation.typhoon_id.in_(source_ids))),
        "main_observation_count": db.scalar(select(func.count()).select_from(TyphoonObservation).where(TyphoonObservation.track_type == "MAIN", TyphoonObservation.typhoon_id.in_(source_ids))),
        "years": [item[0] for item in yearly],
        "yearly": [{"year": item[0], "count": item[1]} for item in yearly],
        "yearly_all": [{"year": item[0], "count": item[1]} for item in yearly_all],
        "provisional_observation_count": db.scalar(select(func.count()).select_from(TyphoonObservation).where(TyphoonObservation.track_type.contains("PROVISIONAL"), TyphoonObservation.typhoon_id.in_(source_ids))),
        "missing_cma_wind_count": db.scalar(select(func.count()).select_from(TyphoonObservation).where(TyphoonObservation.cma_wind_ms.is_(None), TyphoonObservation.typhoon_id.in_(source_ids))),
        "last_import_at": last_import.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if last_import else None,
        "latest_job": job_dict(latest) if latest else None,
        "region_policy": "观测行 BASIN=WP，SEASON 与 UTC 时间均在 2014—2025；台风计数仅包含有 MAIN 轨迹的事件。",
    }


def observation_query(event_id: int, track_type: str, *, deduplicate: bool = False):
    query = select(TyphoonObservation).where(TyphoonObservation.typhoon_id == event_id)
    if track_type != "ALL":
        query = query.where(TyphoonObservation.track_type == track_type)
    if deduplicate and track_type != "ALL":
        latest = select(func.max(TyphoonObservation.id)).where(TyphoonObservation.typhoon_id == event_id, TyphoonObservation.track_type == track_type).group_by(TyphoonObservation.observation_time)
        query = query.where(TyphoonObservation.id.in_(latest))
    return query.order_by(TyphoonObservation.observation_time, TyphoonObservation.id)
