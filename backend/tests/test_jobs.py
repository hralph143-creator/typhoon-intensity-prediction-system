"""后台任务生命周期与跨入口互斥；仅操作 conftest 隔离数据库。"""
from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from backend.app.db.database import SessionLocal, init_db
from backend.app.models.typhoon import ImportJob, SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.services import ibtracs_importer, ibtracs_jobs as jobs
from backend.app.services.ibtracs_download import DownloadCancelled


def wait_until_released(job_id: str, timeout: float = 5) -> None:
    """终态落库后 finally 仍需关闭文件锁，避免跨测试争抢同一任务锁。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with jobs._lock:
            still_signalled = job_id in jobs._signals
        guard = jobs._acquire_process_lock()
        if guard is not None:
            jobs._release_process_lock(guard)
            if not still_signalled:
                return
        time.sleep(0.01)
    raise AssertionError(f"worker did not release task state and lock: {job_id}")


@pytest.fixture(autouse=True)
def clean_job_database():
    init_db()
    with jobs._lock:
        finishing_ids = list(jobs._signals)
    for job_id in finishing_ids:
        wait_until_released(job_id)
    # A preceding API test can observe terminal DB status just before worker finally.
    deadline = time.monotonic() + 5
    while True:
        guard = jobs._acquire_process_lock()
        if guard is not None:
            jobs._release_process_lock(guard)
            break
        assert time.monotonic() < deadline, "previous test left the process guard locked"
        time.sleep(0.01)
    assert not jobs._signals, "previous test left a background worker running"
    with SessionLocal() as db:
        for model in (TyphoonObservation, TyphoonEvent, ImportJob, SourceFile):
            db.execute(delete(model))
        db.commit()
    yield
    with jobs._lock:
        pending = list(jobs._signals.items())
    for _, signal in pending:
        signal.set()
    for job_id, _ in pending:
        wait_until_released(job_id)


def fake_import_report(*args, **kwargs):
    return {"total_records": 4, "valid_records": 2, "skipped_records": 1, "failed_records": 1, "sha256": "a" * 64}


def test_download_transitions_progress_import_and_persists_success(monkeypatch, tmp_path):
    entered, finish_download = threading.Event(), threading.Event()
    import_calls = []

    def slow_download(**kwargs):
        kwargs["progress"]({"downloaded_bytes": 1024, "total_bytes": 2048, "speed_bps": 512.0, "progress": 50.0, "phase": "downloading"})
        entered.set()
        assert finish_download.wait(5)
        return {"path": str(tmp_path / "download.csv"), "filename": "original.csv", "url": "https://example.test/data.csv", "file_size": 2048, "sha256": "a" * 64}

    def imported(*args, **kwargs):
        import_calls.append((args, kwargs))
        return fake_import_report()

    monkeypatch.setattr(jobs, "download_csv", slow_download)
    monkeypatch.setattr(ibtracs_importer, "import_csv", imported)
    job = jobs.start_job("download")
    assert entered.wait(5)
    active = jobs.active_job()
    assert active["id"] == job["id"] and active["status"] == "downloading"
    assert active["downloaded_bytes"] == 1024 and active["progress"] == 50
    finish_download.set()
    result = jobs.wait_for_job(job["id"], timeout=5)
    wait_until_released(job["id"])
    assert result["status"] == result["phase"] == "succeeded"
    assert result["valid_records"] == 2 and result["failed_records"] == 1
    assert result["filename"] == "original.csv" and result["file_hash"] == "a" * 64
    assert result["finished_at"].endswith("Z")
    assert import_calls[0][1]["source_url"] == "https://example.test/data.csv"
    assert jobs.active_job() is None


def test_duplicate_request_is_rejected_while_worker_is_active(monkeypatch):
    entered = threading.Event()

    def wait_for_cancel(**kwargs):
        entered.set()
        assert kwargs["cancel"].wait(5)
        raise DownloadCancelled("test cancelled")

    monkeypatch.setattr(jobs, "download_csv", wait_for_cancel)
    first = jobs.start_job("download")
    assert entered.wait(5)
    with pytest.raises(ValueError, match="已有 IBTrACS 任务"):
        jobs.start_job("download")
    jobs.cancel_job(first["id"])
    result = jobs.wait_for_job(first["id"], timeout=5)
    wait_until_released(first["id"])
    assert result["status"] == "cancelled"
    with SessionLocal() as db:
        assert len(list(db.scalars(select(ImportJob)))) == 1


def test_cooperative_cancel_persists_terminal_status_and_releases_guard(monkeypatch):
    entered = threading.Event()

    def wait_for_cancel(**kwargs):
        entered.set()
        assert kwargs["cancel"].wait(5)
        raise DownloadCancelled("用户取消测试下载")

    monkeypatch.setattr(jobs, "download_csv", wait_for_cancel)
    job = jobs.start_job("download")
    assert entered.wait(5)
    requested = jobs.cancel_job(job["id"])
    assert requested["cancel_requested"] is True
    terminal = jobs.wait_for_job(job["id"], timeout=5)
    wait_until_released(job["id"])
    assert terminal["status"] == "cancelled"
    assert terminal["cancel_requested"] is True
    assert "取消" in terminal["error_message"]
    with SessionLocal() as db:
        persisted = db.get(ImportJob, job["id"])
        assert persisted.cancel_requested and persisted.status == "cancelled"
    assert jobs.active_job() is None


def test_failed_job_does_not_prevent_next_successful_import(monkeypatch, tmp_path):
    def failed_download(**kwargs):
        raise TimeoutError("isolated timeout")

    monkeypatch.setattr(jobs, "download_csv", failed_download)
    failed = jobs.start_job("download")
    terminal = jobs.wait_for_job(failed["id"], timeout=5)
    wait_until_released(failed["id"])
    assert terminal["status"] == "failed"
    assert terminal["error_message"] == "isolated timeout"
    monkeypatch.setattr(ibtracs_importer, "import_csv", fake_import_report)
    following = jobs.start_job("import", path=tmp_path / "unused.csv", filename="next.csv")
    following_result = jobs.wait_for_job(following["id"], timeout=5)
    wait_until_released(following["id"])
    assert following_result["status"] == "succeeded"


def test_recovery_marks_orphaned_active_jobs_interrupted():
    active_ids = []
    with SessionLocal() as db:
        for status in jobs.ACTIVE:
            job_id = str(uuid4())
            active_ids.append(job_id)
            db.add(ImportJob(id=job_id, status=status, phase=status))
        completed_id = str(uuid4())
        db.add(ImportJob(id=completed_id, status="succeeded", phase="succeeded"))
        db.commit()
    jobs.recover_interrupted_jobs()
    with SessionLocal() as db:
        for job_id in active_ids:
            job = db.get(ImportJob, job_id)
            assert job.status == "interrupted" and job.finished_at is not None
            assert "上次服务已停止" in job.error_message
        assert db.get(ImportJob, completed_id).status == "succeeded"


def test_second_file_handle_cannot_enter_and_recovery_skips_other_owner():
    orphan_id = str(uuid4())
    with SessionLocal() as db:
        db.add(ImportJob(id=orphan_id, status="downloading", phase="downloading"))
        db.commit()
    guard = jobs._acquire_process_lock()
    assert guard is not None
    try:
        assert jobs._acquire_process_lock() is None
        jobs.recover_interrupted_jobs()
        with SessionLocal() as db:
            assert db.get(ImportJob, orphan_id).status == "downloading"
        with pytest.raises(ValueError, match="含命令行任务"):
            jobs.start_job("download")
    finally:
        jobs._release_process_lock(guard)
    jobs.recover_interrupted_jobs()
    with SessionLocal() as db:
        assert db.get(ImportJob, orphan_id).status == "interrupted"


def test_import_cleanup_removes_only_the_submitted_temporary_file(monkeypatch, tmp_path):
    temporary = tmp_path / "upload.csv"
    retained = tmp_path / "retained.csv"
    temporary.write_text("test temporary content", encoding="utf-8")
    retained.write_text("retained original", encoding="utf-8")
    monkeypatch.setattr(ibtracs_importer, "import_csv", fake_import_report)
    job = jobs.start_job("import", path=temporary, filename="upload.csv", cleanup=True)
    assert jobs.wait_for_job(job["id"], timeout=5)["status"] == "succeeded"
    wait_until_released(job["id"])
    assert not temporary.exists()
    assert retained.exists()


def test_missing_cancel_target_is_not_silently_accepted():
    with pytest.raises(LookupError, match="任务不存在"):
        jobs.cancel_job("missing-job")


def test_task_signal_observes_cancel_marker_from_another_entry(monkeypatch, tmp_path):
    marker = tmp_path / "external.cancel"
    monkeypatch.setattr(jobs, "_cancel_path", lambda _: marker)
    signal = jobs.TaskSignal(str(uuid4()))
    assert signal.is_set() is False
    try:
        marker.touch()
        assert signal.wait(timeout=0.8) is True
        assert signal.is_set() is True
    finally:
        marker.unlink(missing_ok=True)


def test_cancel_remote_active_job_writes_marker_and_reports_request(monkeypatch, tmp_path):
    job_id = str(uuid4())
    marker = tmp_path / f"ibtracs-{job_id}.cancel"
    monkeypatch.setattr(jobs, "_cancel_path", lambda _: marker)
    with SessionLocal() as db:
        db.add(ImportJob(id=job_id, status="importing", phase="importing"))
        db.commit()
    # The worker belongs to another API/CLI process, so there is no local _signals entry.
    assert job_id not in jobs._signals
    remote_worker_signal = jobs.TaskSignal(job_id)
    try:
        response = jobs.cancel_job(job_id)
        assert marker.exists()
        assert response["status"] == "importing" and response["cancel_requested"] is True
        assert remote_worker_signal.wait(timeout=0.8) is True
        with SessionLocal() as db:
            assert jobs.job_dict(db.get(ImportJob, job_id))["cancel_requested"] is True
    finally:
        marker.unlink(missing_ok=True)


def test_terminal_job_ignores_stale_live_progress_and_cancel_markers(monkeypatch, tmp_path):
    job_id = str(uuid4())
    marker = tmp_path / "late.cancel"
    monkeypatch.setattr(jobs, "_cancel_path", lambda _: marker)
    with SessionLocal() as db:
        db.add(ImportJob(id=job_id, status="succeeded", phase="succeeded", progress=100.0, valid_records=9))
        db.commit()
    with jobs._lock:
        jobs._live[job_id] = {"phase": "importing", "progress": None, "valid_records": 2}
    try:
        marker.touch()
        with SessionLocal() as db:
            rendered = jobs.job_dict(db.get(ImportJob, job_id))
        assert rendered["status"] == rendered["phase"] == "succeeded"
        assert rendered["progress"] == 100 and rendered["valid_records"] == 9
        assert rendered["cancel_requested"] is False
    finally:
        marker.unlink(missing_ok=True)
        with jobs._lock:
            jobs._live.pop(job_id, None)


def test_wait_for_terminal_job_means_guard_has_already_been_released(monkeypatch, tmp_path):
    monkeypatch.setattr(ibtracs_importer, "import_csv", fake_import_report)
    first = jobs.start_job("import", path=tmp_path / "first.csv")
    assert jobs.wait_for_job(first["id"], timeout=5)["status"] == "succeeded"
    # No supplementary sleep/helper is allowed here: immediate resubmission must succeed.
    second = jobs.start_job("import", path=tmp_path / "second.csv")
    assert jobs.wait_for_job(second["id"], timeout=5)["status"] == "succeeded"


def test_cancel_acknowledgement_survives_worker_finishing_before_response(monkeypatch):
    job_id = str(uuid4())
    with SessionLocal() as db:
        db.add(ImportJob(id=job_id, status="importing", phase="importing"))
        db.commit()

    class ImmediatelyConsumedMarker:
        def touch(self):
            # Simulate another process consuming/removing the marker and persisting
            # cancellation between cancel_job's SELECT and its response rendering.
            jobs._save(job_id, status="cancelled", phase="cancelled", cancel_requested=True)

        def exists(self):
            return False

    monkeypatch.setattr(jobs, "_cancel_path", lambda _: ImmediatelyConsumedMarker())
    assert jobs.cancel_job(job_id)["cancel_requested"] is True
