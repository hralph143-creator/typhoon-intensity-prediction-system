"""有界内存、事务化导入；原始 CSV 按哈希留存，重复文件不增加业务数据。"""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.sqlite import insert

from backend.app.core.config import PROJECT_ROOT
from backend.app.db.database import SessionLocal
from backend.app.models.typhoon import SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.services.ibtracs_parser import ImportCancelled, POLICY_VERSION, inspect_csv, iter_csv_records, new_statistics


RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "ibtracs"
BATCH_SIZE = 500


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _retain_original(path: Path, digest: str) -> Path:
    RAW_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if path.resolve().is_relative_to(RAW_DIRECTORY.resolve()):
        # 下载器已在原始数据目录安全落盘，保留带官方原名的缓存文件，避免复制大型CSV。
        return path
    destination = RAW_DIRECTORY / f"{digest}.csv"
    if destination.exists():
        if file_sha256(destination) != digest:
            raise ValueError("已登记原始文件的SHA-256不一致，请检查磁盘文件")
        return destination
    if shutil.disk_usage(RAW_DIRECTORY).free < path.stat().st_size + 64 * 1024 * 1024:
        raise ValueError("磁盘可用空间不足，无法安全保存原始文件")
    temporary = RAW_DIRECTORY / f"{digest}.copying"
    try:
        with path.open("rb") as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if file_sha256(temporary) != digest:
            raise ValueError("留存原始文件时校验失败")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def import_csv(
    path: Path,
    job_id: str | None = None,
    original_filename: str | None = None,
    source_url: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    path = Path(path).resolve()
    if not path.is_file() or path.suffix.lower() != ".csv":
        raise ValueError("请选择存在的 CSV 文件")
    if cancel_check and cancel_check():
        raise ImportCancelled("用户取消导入")
    metadata = inspect_csv(path)
    # Web上传临时文件使用UUID命名，版本应从上传时保留的原始文件名读取。
    named_version = re.search(r"v\d{2}r\d{2}", original_filename or path.name, re.IGNORECASE)
    if named_version:
        metadata["version"] = named_version.group().lower()
    digest = file_sha256(path)
    with SessionLocal() as session:
        existing = session.scalar(select(SourceFile).where(SourceFile.sha256 == digest))
        if existing and existing.status == "imported" and existing.statistics.get("policy_version") == POLICY_VERSION:
            return {**existing.statistics, "source_file_id": existing.id, "sha256": digest, "file_size": existing.file_size, "idempotent": True, "import_seconds": round(time.monotonic() - started, 3)}
    original = _retain_original(path, digest)
    with SessionLocal() as session:
        source_file = session.scalar(select(SourceFile).where(SourceFile.sha256 == digest))
        if source_file is None:
            source_file = SourceFile(
                original_filename=Path(original_filename or path.name).name,
                local_path=str(original), sha256=digest, file_size=path.stat().st_size,
                version=metadata["version"], source_url=source_url, status="registered",
            )
            session.add(source_file)
        session.commit()
        source_id = source_file.id
    stats = new_statistics()
    stats.update(metadata)
    stats.update({"duplicate_records": 0, "conflicting_records": 0, "inserted_records": 0, "source_file_id": source_id, "sha256": digest, "file_size": path.stat().st_size, "job_id": job_id})
    event_ids: dict[str, int] = {}
    try:
        with SessionLocal() as session:
            with session.begin():
                def flush_batch(records: list[dict[str, Any]]) -> None:
                    if not records:
                        return
                    if cancel_check and cancel_check():
                        raise ImportCancelled("用户取消导入，未提交的观测已回滚")
                    rows: list[dict[str, Any]] = []
                    for record in records:
                        sid = record["sid"]
                        if sid not in event_ids:
                            event = session.scalar(select(TyphoonEvent).where(TyphoonEvent.source == "ibtracs", TyphoonEvent.sid == sid))
                            if event is None:
                                event = TyphoonEvent(source="ibtracs", sid=sid, season=record["season"], number=record["number"], name=record["name"], first_observation=record["observation_time"], last_observation=record["observation_time"])
                                session.add(event)
                                session.flush()
                            event_ids[sid] = event.id
                        row = {key: value for key, value in record.items() if key not in {"sid", "season", "number", "name"}}
                        row.update(typhoon_id=event_ids[sid], source_file_id=source_id)
                        rows.append(row)
                    keys = {(row["typhoon_id"], row["observation_time"].replace(tzinfo=None), row["track_type"]) for row in rows}
                    hashes: dict[tuple, set[str]] = {}
                    prior = session.execute(select(TyphoonObservation.typhoon_id, TyphoonObservation.observation_time, TyphoonObservation.track_type, TyphoonObservation.row_hash).where(tuple_(TyphoonObservation.typhoon_id, TyphoonObservation.observation_time, TyphoonObservation.track_type).in_(keys)))
                    for typhoon_id, observed, track, row_hash in prior:
                        hashes.setdefault((typhoon_id, observed, track), set()).add(row_hash)
                    conflict_keys: set[tuple] = set()
                    for row in rows:
                        key = (row["typhoon_id"], row["observation_time"].replace(tzinfo=None), row["track_type"])
                        row_hashes = hashes.setdefault(key, set())
                        if row_hashes and row["row_hash"] not in row_hashes:
                            conflict_keys.add(key)
                            stats["conflicting_records"] += 1
                        row_hashes.add(row["row_hash"])
                    for row in rows:
                        key = (row["typhoon_id"], row["observation_time"].replace(tzinfo=None), row["track_type"])
                        if key in conflict_keys:
                            row["quality_flags"] = list(dict.fromkeys([*row["quality_flags"], "conflicting_observation"]))
                    if conflict_keys:
                        for previous in session.scalars(select(TyphoonObservation).where(tuple_(TyphoonObservation.typhoon_id, TyphoonObservation.observation_time, TyphoonObservation.track_type).in_(conflict_keys))):
                            previous.quality_flags = list(dict.fromkeys([*previous.quality_flags, "conflicting_observation"]))
                        session.flush()
                    result = session.execute(insert(TyphoonObservation).values(rows).on_conflict_do_nothing(index_elements=["typhoon_id", "observation_time", "track_type", "row_hash"]))
                    inserted = result.rowcount
                    stats["inserted_records"] += inserted
                    stats["duplicate_records"] += len(rows) - inserted
                    if progress_callback:
                        progress_callback(dict(stats))

                batch: list[dict[str, Any]] = []
                for record in iter_csv_records(original, stats=stats, cancel_check=cancel_check, progress_callback=progress_callback):
                    batch.append(record)
                    if len(batch) >= BATCH_SIZE:
                        flush_batch(batch)
                        batch.clear()
                flush_batch(batch)
                # MAIN同一时刻按最新导入版本聚合，与默认地图/曲线采用同一选择规则。
                for event_id in event_ids.values():
                    event = session.get(TyphoonEvent, event_id)
                    total, all_first, all_last = session.execute(select(func.count(), func.min(TyphoonObservation.observation_time), func.max(TyphoonObservation.observation_time)).where(TyphoonObservation.typhoon_id == event_id)).one()
                    latest_main = select(func.max(TyphoonObservation.id)).where(TyphoonObservation.typhoon_id == event_id, TyphoonObservation.track_type == "MAIN").group_by(TyphoonObservation.observation_time)
                    summary = session.execute(select(func.min(TyphoonObservation.observation_time), func.max(TyphoonObservation.observation_time), func.max(TyphoonObservation.cma_wind_ms), func.min(TyphoonObservation.cma_pressure), func.max(TyphoonObservation.cma_category).filter(TyphoonObservation.cma_category.between(1, 6))).where(TyphoonObservation.id.in_(latest_main))).one()
                    event.observation_count = total
                    if summary[0] is not None:
                        event.first_observation, event.last_observation = summary[0], summary[1]
                    else:
                        event.first_observation, event.last_observation = all_first, all_last
                    event.maximum_wind, event.minimum_pressure, event.maximum_category = summary[2:]
                    event.track_types = list(session.scalars(select(TyphoonObservation.track_type).where(TyphoonObservation.typhoon_id == event_id).distinct()))
                stats["typhoon_count"] = len(event_ids)
                stats["main_track_event_count"] = session.scalar(select(func.count(func.distinct(TyphoonObservation.typhoon_id))).where(TyphoonObservation.source_file_id == source_id, TyphoonObservation.track_type == "MAIN")) or 0
                stats["import_seconds"] = round(time.monotonic() - started, 3)
                stats["idempotent"] = False
                stats["summary_policy"] = "event extrema from latest imported MAIN record per UTC timestamp; lifecycle from MAIN or all observations if MAIN absent; observation_count includes all retained track/conflict variants"
                source_file = session.get(SourceFile, source_id)
                source_file.status = "imported"
                source_file.imported_at = datetime.now(UTC)
                source_file.statistics = dict(stats)
                if cancel_check and cancel_check():
                    raise ImportCancelled("用户取消导入，未提交的观测已回滚")
    except BaseException:
        with SessionLocal() as session:
            source_file = session.get(SourceFile, source_id)
            if source_file:
                source_file.status = "failed"
                session.commit()
        raise
    return stats
