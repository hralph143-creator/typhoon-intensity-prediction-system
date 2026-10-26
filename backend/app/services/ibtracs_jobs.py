"""单机后台任务：任务落库、内存进度覆盖、合作式取消和重启恢复。"""
from __future__ import annotations

import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.core.config import settings
from backend.app.models.typhoon import ImportJob
from backend.app.services.ibtracs_download import DownloadCancelled, download_csv


ACTIVE = ("queued", "downloading", "importing")
_lock = threading.RLock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ibtracs")
_signals: dict[str, threading.Event] = {}
_live: dict[str, dict] = {}


def _cancel_path(job_id: str) -> Path:
    base = settings.database_path.parent if settings.database_path else settings.raw_data_dir
    return base / f"ibtracs-{job_id}.cancel"


class TaskSignal(threading.Event):
    """跨 API/CLI 的取消信号；避免导入事务期间额外争用 SQLite 写锁。"""
    def __init__(self, job_id):
        super().__init__()
        self.cancel_path = _cancel_path(job_id)
        self.last_checked = 0.0

    def is_set(self):
        if not super().is_set() and time.monotonic() - self.last_checked >= 0.2:
            self.last_checked = time.monotonic()
            if self.cancel_path.exists():
                super().set()
        return super().is_set()

    def wait(self, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            super().wait(min(0.2, max(0, deadline - time.monotonic())) if deadline is not None else 0.2)
        return True


def _acquire_process_lock():
    """API 与 CLI 共用数据库时也只能有一个数据写入任务。"""
    database_path = settings.database_path
    lock_path = database_path.with_suffix(".ibtracs.lock") if database_path else settings.raw_data_dir / "task.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.seek(0, 2) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _release_process_lock(handle):
    if handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def utc_iso(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return value


def job_dict(job: ImportJob) -> dict:
    result = {column.name: utc_iso(getattr(job, column.name)) for column in ImportJob.__table__.columns}
    with _lock:
        if job.status in ACTIVE:
            result.update(_live.get(job.id, {}))
            if _cancel_path(job.id).exists():
                result["cancel_requested"] = True
    return result


def recover_interrupted_jobs() -> None:
    guard = _acquire_process_lock()
    if guard is None:
        return  # 另一进程仍在处理，不把活跃任务误标为中断
    try:
        _recover()
    finally:
        _release_process_lock(guard)


def _recover() -> None:
    with _lock, SessionLocal() as db:
        for job in db.scalars(select(ImportJob).where(ImportJob.status.in_(ACTIVE))):
            if job.id not in _signals:
                job.status = "interrupted"
                job.phase = "interrupted"
                job.finished_at = datetime.now(UTC)
                job.error_message = "上次服务已停止；未提交的导入已回滚，可重新发起任务，下载将尝试复用断点。"
        db.commit()


def _save(job_id: str, **fields) -> None:
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        if job:
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            db.commit()


def active_job() -> dict | None:
    with SessionLocal() as db:
        job = db.scalar(select(ImportJob).where(ImportJob.status.in_(ACTIVE)).order_by(ImportJob.started_at.desc()))
        return job_dict(job) if job else None


def start_job(kind: str, *, path: Path | None = None, filename: str | None = None, force: bool = False, cleanup: bool = False) -> dict:
    with _lock:
        guard = _acquire_process_lock()
        if guard is None:
            raise ValueError("已有 IBTrACS 任务运行中（含命令行任务）")
        try:
            current = active_job()
            if current:
                raise ValueError(f"已有 IBTrACS 任务运行中：{current['id']}")
            job_id = str(uuid4())
            signal = TaskSignal(job_id)
            with SessionLocal() as db:
                job = ImportJob(id=job_id, kind=kind, filename=filename, status="queued", phase="queued")
                db.add(job)
                db.commit()
                result = job_dict(job)
            _signals[job_id] = signal
            _executor.submit(_run, job_id, kind, path, filename, force, cleanup, signal, guard)
            return result
        except BaseException:
            _release_process_lock(guard)
            raise


def cancel_job(job_id: str) -> dict:
    acknowledged = False
    with _lock:
        signal = _signals.get(job_id)
        if signal:
            signal.set()
            _live.setdefault(job_id, {}).update(cancel_requested=True)
            acknowledged = True
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        if not job:
            raise LookupError("任务不存在")
        if job.status in ACTIVE:
            _cancel_path(job_id).touch()
            acknowledged = True
        result = job_dict(job)
        # 工作线程可能在上面的状态查询与响应序列化之间完成取消，
        # 此时内存进度和取消标记已清理。响应仍应确认本次请求已被接收。
        if acknowledged:
            result["cancel_requested"] = True
        return result


def _run(job_id, kind, path, filename, force, cleanup, signal, guard):
    # 导入使用一个数据库事务，因此期间只更新内存进度，避免争抢 SQLite 写锁。
    from backend.app.services.ibtracs_importer import import_csv
    last_saved = 0.0

    def on_progress(values):
        nonlocal last_saved
        with _lock:
            _live.setdefault(job_id, {}).update(values)
        if kind == "download" and values.get("phase") in ("downloading", "retrying") and time.monotonic() - last_saved > 1:
            _save(job_id, **{key: value for key, value in values.items() if key in {"phase", "downloaded_bytes", "total_bytes", "speed_bps", "progress"}})
            last_saved = time.monotonic()

    try:
        if signal.is_set():
            raise DownloadCancelled("任务已取消")
        source_url = None
        if kind == "download":
            _save(job_id, status="downloading", phase="downloading")
            downloaded = download_csv(force=force, cancel=signal, progress=on_progress)
            path = Path(downloaded["path"])
            filename = downloaded["filename"]
            source_url = downloaded["url"]
            _save(job_id, filename=filename, downloaded_bytes=downloaded["file_size"], file_hash=downloaded["sha256"])
        if signal.is_set():
            raise DownloadCancelled("任务已取消")
        _save(job_id, status="importing", phase="importing", progress=None, error_message=None)
        on_progress({"phase": "importing", "progress": None, "speed_bps": 0})
        result = import_csv(path, job_id=job_id, original_filename=filename, source_url=source_url, cancel_check=signal.is_set, progress_callback=on_progress)
        _save(job_id, status="succeeded", phase="succeeded", progress=100.0, error_message=None, finished_at=datetime.now(UTC), statistics=result, source_file_id=result.get("source_file_id"), file_hash=result.get("sha256"), total_records=result.get("total_records", 0), valid_records=result.get("valid_records", 0), skipped_records=result.get("skipped_records", 0), failed_records=result.get("failed_records", 0))
    except Exception as exc:
        cancelled = signal.is_set() or isinstance(exc, DownloadCancelled)
        _save(job_id, status="cancelled" if cancelled else "failed", phase="cancelled" if cancelled else "failed", finished_at=datetime.now(UTC), error_message=str(exc), cancel_requested=cancelled, speed_bps=0)
    finally:
        try:
            if cleanup and path:
                path.unlink(missing_ok=True)
        finally:
            _cancel_path(job_id).unlink(missing_ok=True)
            _release_process_lock(guard)
            with _lock:
                _signals.pop(job_id, None)
                _live.pop(job_id, None)


def wait_for_job(job_id: str, timeout: float = 300) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            result = job_dict(db.get(ImportJob, job_id))
        if result["status"] not in ACTIVE:
            with _lock:
                finished_locally = job_id not in _signals
            if finished_locally:
                return result
        time.sleep(0.2)
    raise TimeoutError("后台任务仍在运行，请通过任务接口继续查询")
