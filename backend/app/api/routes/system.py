import platform
import sys

from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import Response,FileResponse
from pydantic import BaseModel,Field

from backend.app.core.config import PROJECT_ROOT, settings
from backend.app.schemas.common import ApiResponse
from backend.app.schemas.system import RuntimeInfo
from backend.app.services.system_management import backup_file,cleanup_temporary,create_backup,delete_backup,exported_log,list_backups,maintenance_preview,read_logs,restore_backup,runtime_status,verify_backup


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

class BackupCreate(BaseModel):
    name:str=Field(default="手动备份",max_length=200)

def ok(data,message="请求成功"):return {"success":True,"message":message,"data":data}
def fail(exc):
    if isinstance(exc,LookupError):raise HTTPException(404,str(exc))
    raise HTTPException(409,str(exc))

@router.get("/status")
def status():return ok(runtime_status())
@router.get("/logs")
def logs(level:str|None=None,keyword:str|None=None,limit:int=Query(200,ge=1,le=500)):return ok(read_logs(level,keyword,limit))
@router.get("/logs/download")
def logs_download():
    try:return Response(exported_log(),media_type="text/plain; charset=utf-8",headers={"Content-Disposition":"attachment; filename=backend.log"})
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.get("/backups")
def backups():return ok(list_backups())
@router.post("/backups",status_code=201)
def backup_create(payload:BackupCreate):
    try:return ok(create_backup(payload.name),"备份已创建并校验")
    except ValueError as exc:fail(exc)
@router.post("/backups/{backup_id}/verify")
def backup_verify(backup_id:str):
    try:return ok(verify_backup(backup_id),"备份校验通过")
    except (LookupError,ValueError) as exc:fail(exc)
@router.get("/backups/{backup_id}/download")
def backup_download(backup_id:str):
    try:
        path=backup_file(backup_id);return FileResponse(path,media_type="application/vnd.sqlite3",filename=f"cloudwave-backup-{backup_id}.sqlite3")
    except (LookupError,ValueError) as exc:fail(exc)
@router.post("/backups/{backup_id}/restore")
def backup_restore(backup_id:str,confirmed:bool=False):
    try:return ok(restore_backup(backup_id,confirmed),"恢复完成")
    except (LookupError,ValueError) as exc:fail(exc)
@router.delete("/backups/{backup_id}")
def backup_delete(backup_id:str,confirmed:bool=False):
    try:delete_backup(backup_id,confirmed);return ok({"id":backup_id},"备份已删除")
    except (LookupError,ValueError) as exc:fail(exc)
@router.get("/maintenance/preview")
def maintenance():return ok(maintenance_preview())
@router.post("/maintenance/cleanup")
def cleanup(confirmed:bool=False):
    try:return ok(cleanup_temporary(confirmed),"临时文件已清理")
    except ValueError as exc:fail(exc)

