import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import PROJECT_ROOT, settings
from backend.app.db.database import get_db
from backend.app.models.typhoon import ImportJob, SourceFile
from backend.app.schemas.common import ApiResponse
from backend.app.services.ibtracs_download import validate_csv
from backend.app.services.ibtracs_jobs import active_job, cancel_job, job_dict, start_job
from backend.app.services.typhoon_queries import source_file_dict, statistics

router = APIRouter(prefix="/ibtracs", tags=["IBTrACS下载与导入"])


class DownloadRequest(BaseModel):
    force: bool = False


class ReimportRequest(BaseModel):
    file_id: int


@router.get("/status", summary="本地文件与已入库数据状态")
def status(db: Session = Depends(get_db)):
    stats = statistics(db)
    files = list(db.scalars(select(SourceFile).where(SourceFile.source == "ibtracs").order_by(SourceFile.acquired_at.desc())))
    return ApiResponse(data={"source": "ibtracs", "official_url": "https://www.ncei.noaa.gov/products/international-best-track-archive", "download_url": settings.ibtracs_url, "connected": stats["observation_count"] > 0, "file_count": len(files), "imported_files": [source_file_dict(item) for item in files], "typhoon_count": stats["typhoon_count"], "observation_count": stats["observation_count"], "last_import_at": stats["last_import_at"], "active_job": active_job()})


@router.post("/download", status_code=202, summary="后台下载官方WP文件并导入2014—2025年研究记录")
def download(payload: DownloadRequest | None = None):
    try:
        return ApiResponse(data=start_job("download", filename="ibtracs.WP.list.v04r01.csv", force=payload.force if payload else False))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/import", status_code=202, summary="上传CSV后后台导入；最大512MiB，分块接收不整体读入内存")
async def upload_import(file: UploadFile = File(...)):
    if active_job():
        raise HTTPException(409, "已有 IBTrACS 任务运行中")
    name = Path((file.filename or "uploaded.csv").replace("\\", "/")).name
    if not name.lower().endswith(".csv"):
        raise HTTPException(422, "请选择 .csv 文件")
    folder = PROJECT_ROOT / "data" / "cache" / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid4()}.csv"
    received = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                received += len(chunk)
                if received > settings.upload_max_bytes:
                    raise HTTPException(413, "文件超过允许的最大上传大小")
                if shutil.disk_usage(folder).free < len(chunk) + 64 * 1024 * 1024:
                    raise HTTPException(507, "磁盘空间不足")
                output.write(chunk)
        validate_csv(target)
        try:
            job = start_job("import", path=target, filename=name, cleanup=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return ApiResponse(data=job)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except (ValueError, UnicodeError) as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()


@router.post("/reimport", status_code=202, summary="按已登记原始文件重新导入，内容哈希保证幂等")
def reimport(payload: ReimportRequest, db: Session = Depends(get_db)):
    source_file = db.get(SourceFile, payload.file_id)
    if not source_file:
        raise HTTPException(404, "原始文件记录不存在")
    path = Path(source_file.local_path)
    if not path.is_file():
        raise HTTPException(404, "登记的原始文件已不存在，请重新上传")
    try:
        return ApiResponse(data=start_job("import", path=path, filename=source_file.original_filename))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/jobs", summary="分页查看持久化下载/导入记录")
def jobs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    items = db.scalars(select(ImportJob).order_by(ImportJob.started_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return ApiResponse(data={"items": [job_dict(item) for item in items], "total": db.scalar(select(func.count()).select_from(ImportJob)), "page": page, "page_size": page_size})


@router.get("/jobs/{job_id}")
def job(job_id: str, db: Session = Depends(get_db)):
    item = db.get(ImportJob, job_id)
    if not item:
        raise HTTPException(404, "任务不存在")
    return ApiResponse(data=job_dict(item))


@router.post("/jobs/{job_id}/cancel", summary="请求合作式取消，导入未提交业务记录将回滚")
def cancel(job_id: str):
    try:
        return ApiResponse(data=cancel_job(job_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
