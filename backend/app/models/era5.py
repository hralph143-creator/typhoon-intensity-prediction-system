"""第四阶段 ERA5 原始文件、任务与时空样本元数据。"""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Era5File(Base):
    __tablename__ = "era5_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    local_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    file_size: Mapped[int] = mapped_column(Integer)
    dataset: Mapped[str] = mapped_column(String(96), default="reanalysis-era5-single-levels")
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="valid", index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Era5DownloadJob(Base):
    __tablename__ = "era5_download_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    typhoon_id: Mapped[int | None] = mapped_column(ForeignKey("typhoon_events.id"), index=True)
    sid: Mapped[str | None] = mapped_column(String(32))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(48), default="queued")
    progress: Mapped[float | None] = mapped_column(Float)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("era5_files.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WindFieldSample(Base):
    __tablename__ = "wind_field_samples"
    __table_args__ = (UniqueConstraint("sid", "observation_time", "processing_version", name="uq_wind_field_sample"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    era5_file_id: Mapped[int] = mapped_column(ForeignKey("era5_files.id"), index=True)
    typhoon_id: Mapped[int] = mapped_column(ForeignKey("typhoon_events.id"), index=True)
    sid: Mapped[str] = mapped_column(String(32), index=True)
    observation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    center_latitude: Mapped[float] = mapped_column(Float)
    center_longitude: Mapped[float] = mapped_column(Float)
    local_path: Mapped[str] = mapped_column(Text)
    shape: Mapped[list[int]] = mapped_column(JSON, default=lambda: [2, 31, 31])
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_status: Mapped[str] = mapped_column(String(24), default="valid")
    processing_version: Mapped[str] = mapped_column(String(32), default="era5-crop-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SpatiotemporalSample(Base):
    __tablename__ = "spatiotemporal_samples"
    __table_args__ = (
        UniqueConstraint("sid", "forecast_time", "processing_version", name="uq_spatiotemporal_sample"),
        Index("ix_spatiotemporal_split_time", "split", "forecast_time"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    typhoon_id: Mapped[int] = mapped_column(ForeignKey("typhoon_events.id"), index=True)
    sid: Mapped[str] = mapped_column(String(32), index=True)
    forecast_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    split: Mapped[str] = mapped_column(String(24), index=True)
    target_wind: Mapped[float] = mapped_column(Float)
    temporal_features: Mapped[list[float]] = mapped_column(JSON)
    wind_field_ids: Mapped[list[int]] = mapped_column(JSON)
    local_path: Mapped[str] = mapped_column(Text)
    shape: Mapped[list[int]] = mapped_column(JSON, default=lambda: [4, 2, 31, 31])
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    processing_version: Mapped[str] = mapped_column(String(32), default="spatiotemporal-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Era5SampleBatch(Base):
    """受资源预算约束、可恢复的公共 ARCO 样本准备批次。"""
    __tablename__ = "era5_sample_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    requested: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    estimated_bytes: Mapped[int] = mapped_column(Integer, default=0)
    actual_bytes: Mapped[int] = mapped_column(Integer, default=0)
    estimated_remote_bytes: Mapped[int] = mapped_column(Integer, default=0)
    remote_requests: Mapped[int] = mapped_column(Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    processing_version: Mapped[str] = mapped_column(String(32), default="spatiotemporal-v2")
    source_id: Mapped[str | None] = mapped_column(String(32))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
