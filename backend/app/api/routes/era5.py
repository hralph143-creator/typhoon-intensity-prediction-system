from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.services.era5_service import (build_spatiotemporal_samples, cancel_job, connection_test, create_download_job,
    credential_status, list_files, list_jobs, preview_plans, register_file, retry_job, sample_statistics)

router = APIRouter(prefix="/era5", tags=["ERA5 风场"])


def ok(data, message="请求成功"): return {"success":True,"message":message,"data":data}


class DownloadRequest(BaseModel):
    request: dict
    typhoon_id: int | None = None
    sid: str | None = Field(default=None,max_length=32)


@router.get("/status")
def status(): return ok({**credential_status(),"disk_budget_gb":settings.era5_disk_budget_gb,"files":len(list_files())})


@router.post("/connection-test")
def test_connection(): return ok(connection_test())


@router.get("/plans")
def plans(limit:int=Query(3,ge=1,le=10)): return ok(preview_plans(limit))


@router.post("/jobs",status_code=202)
def create_job(payload:DownloadRequest):
    try:return ok(create_download_job(payload.model_dump()),"任务已登记")
    except ValueError as exc:raise HTTPException(409,str(exc))


@router.get("/jobs")
def jobs():return ok(list_jobs())


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id:str):
    try:return ok(cancel_job(job_id),"已请求取消；CDS 服务端处理阶段可能需等待返回后生效")
    except LookupError as exc:raise HTTPException(404,str(exc))


@router.post("/jobs/{job_id}/retry",status_code=202)
def retry(job_id:str):
    try:return ok(retry_job(job_id),"重试任务已创建")
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))


@router.post("/import")
async def import_netcdf(file:UploadFile=File(...)):
    name=Path(file.filename or "era5.nc").name
    if not name.lower().endswith((".nc",".nc4")):raise HTTPException(415,"仅支持 NetCDF 文件（.nc/.nc4）")
    with NamedTemporaryFile(suffix=".nc",delete=False) as temporary:
        path=Path(temporary.name); size=0
        while chunk:=await file.read(1024*1024):
            size+=len(chunk)
            if size>settings.upload_max_bytes:path.unlink(missing_ok=True);raise HTTPException(413,"上传文件过大")
            temporary.write(chunk)
    try:return ok(register_file(path,name),"NetCDF 已归档并通过质量检查")
    except ValueError as exc:raise HTTPException(422,str(exc))
    finally:path.unlink(missing_ok=True)


@router.get("/files")
def files():return ok(list_files())


@router.post("/samples/build")
def build(limit:int|None=Query(None,ge=1,le=10000)):
    return ok(build_spatiotemporal_samples(limit),"时空样本构建完成")


@router.get("/samples/statistics")
def statistics():return ok(sample_statistics())
