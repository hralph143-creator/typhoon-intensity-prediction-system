"""受控的运行状态、日志、SQLite 备份与临时文件维护。"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import sqlite3
from datetime import UTC,datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func,select,text

from backend.app.core.config import PROJECT_ROOT,settings
from backend.app.db.database import SessionLocal,engine,init_db
from backend.app.models.era5 import Era5DownloadJob
from backend.app.models.ml import TrainingExperiment
from backend.app.models.report import AnalysisReport,SystemBackup
from backend.app.models.typhoon import ImportJob

logger=logging.getLogger(__name__)
ACTIVE=("queued","running","downloading","processing","generating")
SECRET_PATTERN=re.compile(r"(?i)(api[_-]?key|token|password|authorization)(\s*[:=]\s*)([^\s,;]+)")

def _sha256(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()

def _inside(path:Path,root:Path)->bool:
    try:path.resolve().relative_to(root.resolve());return True
    except ValueError:return False

def _schema_version(path:Path)->int:
    with sqlite3.connect(path) as connection:
        result=connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0]!="ok":raise ValueError("SQLite 完整性检查未通过")
        found=connection.execute("SELECT max(version) FROM schema_migrations").fetchone()
        return int(found[0] or 0)

def runtime_status()->dict:
    db_path=settings.database_path;usage=shutil.disk_usage(PROJECT_ROOT)
    with SessionLocal() as db:
        db.execute(text("SELECT 1"));report_count=db.scalar(select(func.count()).select_from(AnalysisReport)) or 0
    db_size=sum(p.stat().st_size for p in [db_path,Path(str(db_path)+"-wal"),Path(str(db_path)+"-shm")] if p and p.exists()) if db_path else 0
    return {"backend":"online","database":"connected","database_size":db_size,"disk_total":usage.total,"disk_used":usage.used,"disk_free":usage.free,"report_count":report_count,"paths":{"database":str(db_path),"reports":str(settings.report_dir),"backups":str(settings.backup_dir),"logs":str(PROJECT_ROOT/"logs")}}

def read_logs(level:str|None=None,keyword:str|None=None,limit:int=200)->list[dict]:
    path=PROJECT_ROOT/"logs"/"backend.log"
    if not path.exists():return []
    lines=path.read_text("utf-8",errors="replace").splitlines()[-3000:];items=[]
    for line in reversed(lines):
        parts=line.split(" | ",3)
        message=parts[3] if len(parts)>3 else line
        row={"timestamp":parts[0] if len(parts)>0 else "","level":parts[1] if len(parts)>1 else "UNKNOWN","logger":parts[2] if len(parts)>2 else "","message":SECRET_PATTERN.sub(r"\1\2***",message)}
        if level and row["level"]!=level.upper():continue
        if keyword and keyword.lower() not in line.lower():continue
        items.append(row)
        if len(items)>=limit:break
    return items

def log_path()->Path:return PROJECT_ROOT/"logs"/"backend.log"

def exported_log()->bytes:
    path=log_path()
    if not path.exists():raise LookupError("日志文件不存在")
    return "\n".join(SECRET_PATTERN.sub(r"\1\2***",line) for line in path.read_text("utf-8",errors="replace").splitlines()).encode("utf-8-sig")

def create_backup(name:str="手动备份",backup_type:str="manual")->dict:
    source=settings.database_path
    if not source or not source.exists():raise ValueError("当前不是可备份的本地 SQLite 数据库")
    settings.backup_dir.mkdir(parents=True,exist_ok=True);backup_id=str(uuid4());target=settings.backup_dir/f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{backup_id}.sqlite3"
    with sqlite3.connect(source) as src,sqlite3.connect(target) as dst:src.backup(dst)
    version=_schema_version(target);checksum=_sha256(target)
    with SessionLocal() as db:
        row=SystemBackup(id=backup_id,backup_name=name[:200],backup_path=str(target),backup_type=backup_type,file_size=target.stat().st_size,checksum=checksum,schema_version=version,verification_status="verified");db.add(row);db.commit();result=backup_dict(row)
    logger.info("数据库备份创建成功 id=%s type=%s",backup_id,backup_type);return result

def backup_dict(row:SystemBackup)->dict:return {c.name:(getattr(row,c.name).isoformat()+"Z" if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in SystemBackup.__table__.columns if c.name!="backup_path"}
def list_backups()->list[dict]:
    with SessionLocal() as db:return [backup_dict(x) for x in db.scalars(select(SystemBackup).order_by(SystemBackup.created_at.desc()))]

def verify_backup(backup_id:str)->dict:
    with SessionLocal() as db:
        row=db.get(SystemBackup,backup_id)
        if not row:raise LookupError("备份不存在")
        result=backup_dict(row);raw_path=row.backup_path;checksum=row.checksum;schema_version=row.schema_version
    path=Path(raw_path)
    if not _inside(path,settings.backup_dir) or not path.is_file():raise ValueError("备份文件路径无效")
    version=_schema_version(path);valid=_sha256(path)==checksum and version==schema_version
    if not valid:raise ValueError("备份校验和或架构版本不一致")
    return {**result,"integrity":"ok"}

def _active_jobs()->int:
    with SessionLocal() as db:
        return sum(db.scalar(select(func.count()).select_from(model).where(column.in_(ACTIVE))) or 0 for model,column in [(ImportJob,ImportJob.status),(TrainingExperiment,TrainingExperiment.status),(Era5DownloadJob,Era5DownloadJob.status),(AnalysisReport,AnalysisReport.report_status)])

def restore_backup(backup_id:str,confirmed:bool)->dict:
    if not confirmed:raise ValueError("恢复数据库需要明确二次确认")
    if _active_jobs():raise ValueError("存在运行中的导入、训练、下载或报告任务，不能恢复")
    verified=verify_backup(backup_id)
    with SessionLocal() as db:
        row=db.get(SystemBackup,backup_id);path=Path(row.backup_path)
    current=settings.database_path
    if not current:raise ValueError("当前不是本地 SQLite 数据库")
    current_version=_schema_version(current)
    if verified["schema_version"]!=current_version:raise ValueError("备份架构版本与当前系统不一致")
    safety=create_backup("恢复前自动备份","pre_restore")
    with SessionLocal() as db:
        safety_row=db.get(SystemBackup,safety["id"])
        safety_values={c.name:getattr(safety_row,c.name) for c in SystemBackup.__table__.columns}
    engine.dispose()
    with sqlite3.connect(path) as src,sqlite3.connect(current) as dst:src.backup(dst)
    init_db()
    with SessionLocal() as db:db.merge(SystemBackup(**safety_values));db.commit()
    logger.warning("数据库已从受控备份恢复 id=%s safety=%s",backup_id,safety["id"])
    return {"restored_backup_id":backup_id,"safety_backup_id":safety["id"]}

def delete_backup(backup_id:str,confirmed:bool):
    if not confirmed:raise ValueError("删除备份需要二次确认")
    with SessionLocal() as db:
        row=db.get(SystemBackup,backup_id)
        if not row:raise LookupError("备份不存在")
        path=Path(row.backup_path)
        if not _inside(path,settings.backup_dir):raise ValueError("备份文件路径无效")
        db.delete(row);db.commit()
    path.unlink(missing_ok=True)

def maintenance_candidates()->list[Path]:
    roots=(PROJECT_ROOT/"data"/"cache",PROJECT_ROOT/".tmp")
    return [p for root in roots if root.exists() for p in root.rglob("*") if p.is_file() and _inside(p,root)]

def maintenance_preview()->dict:
    files=maintenance_candidates();return {"file_count":len(files),"total_bytes":sum(x.stat().st_size for x in files),"roots":[str(PROJECT_ROOT/"data"/"cache"),str(PROJECT_ROOT/".tmp")]}

def cleanup_temporary(confirmed:bool)->dict:
    if not confirmed:raise ValueError("清理临时文件需要二次确认")
    files=maintenance_candidates();size=sum(x.stat().st_size for x in files)
    for path in files:path.unlink(missing_ok=True)
    logger.info("临时文件清理完成 count=%s bytes=%s",len(files),size);return {"deleted_files":len(files),"deleted_bytes":size}
