from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.services.era5_service import (build_spatiotemporal_samples, cancel_job, connection_test, create_download_job,
    cancel_public_batch, create_public_batch, credential_status, download_public_sample, get_public_batch, list_files,
    list_jobs, list_public_batches, preview_plans, public_batch_preview, register_file, resume_public_batch, retry_job, sample_statistics)
from backend.app.services.phase8_service import data_quality_audit, freeze_dataset

router = APIRouter(prefix="/era5", tags=["ERA5 风场"])


def ok(data, message="请求成功"): return {"success":True,"message":message,"data":data}


class DownloadRequest(BaseModel):
    request: dict
    typhoon_id: int | None = None
    sid: str | None = Field(default=None,max_length=32)


@router.get("/status")
def status():
    files = list_files()
    credentials = credential_status()
    if files and not credentials["configured"]:
        credentials["message"] = "公共 ARCO-ERA5 已连接；CDS 个人令牌仅用于官方 API 扩展下载。"
    return ok({**credentials, "connected": bool(files), "access_mode": "public_arco" if files else None,
        "public_arco_available": True, "disk_budget_gb": settings.era5_disk_budget_gb, "files": len(files)})


@router.post("/public-sample")
def public_sample():
    try:
        return ok(download_public_sample(), "公共 ARCO-ERA5 真实风场下载并构建完成")
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(502, f"公共 ERA5 下载失败：{exc}") from exc


@router.get("/public-batches/preview")
def batch_preview(per_split:int=Query(2,ge=1,le=10)):return ok(public_batch_preview(per_split))


@router.post("/public-batches",status_code=202)
def create_batch(per_split:int=Query(2,ge=1,le=10)):
    try:return ok(create_public_batch(per_split),"公共 ERA5 受控批次已创建")
    except ValueError as exc:raise HTTPException(409,str(exc))


@router.get("/public-batches")
def batches():return ok(list_public_batches())


@router.get("/public-batches/{batch_id}")
def batch(batch_id:str):
    try:return ok(get_public_batch(batch_id))
    except LookupError as exc:raise HTTPException(404,str(exc))


@router.post("/public-batches/{batch_id}/cancel")
def cancel_batch(batch_id:str):
    try:return ok(cancel_public_batch(batch_id),"已请求取消批次")
    except LookupError as exc:raise HTTPException(404,str(exc))


@router.post("/public-batches/{batch_id}/resume",status_code=202)
def resume_batch(batch_id:str):
    try:return ok(resume_public_batch(batch_id),"批次已从断点恢复")
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))


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


@router.get("/samples/audit")
def phase8_audit():return ok(data_quality_audit())


@router.post("/samples/freeze")
def freeze_phase8_dataset():
    try:return ok(freeze_dataset(),"第八阶段数据清单已冻结")
    except ValueError as exc:raise HTTPException(409,str(exc))
