"""可追溯的 IBTrACS 文件、任务与历史观测模型。"""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceFile(Base):
    __tablename__ = "source_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="ibtracs", index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    local_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    file_size: Mapped[int] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(32), default="v04r01")
    source_url: Mapped[str | None] = mapped_column(Text)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="registered")
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ImportJob(Base):
    __tablename__ = "data_import_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="ibtracs")
    kind: Mapped[str] = mapped_column(String(32), default="import")
    filename: Mapped[str | None] = mapped_column(String(255))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(32), default="queued")
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    valid_records: Mapped[int] = mapped_column(Integer, default=0)
    skipped_records: Mapped[int] = mapped_column(Integer, default=0)
    failed_records: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int | None] = mapped_column(Integer)
    speed_bps: Mapped[float] = mapped_column(Float, default=0)
    progress: Mapped[float | None] = mapped_column(Float)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("source_files.id"))
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TyphoonEvent(Base):
    __tablename__ = "typhoon_events"
    __table_args__ = (UniqueConstraint("source", "sid", name="uq_event_source_sid"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="ibtracs")
    sid: Mapped[str] = mapped_column(String(32), index=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100), index=True)
    first_observation: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observation: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    maximum_wind: Mapped[float | None] = mapped_column(Float)
    minimum_pressure: Mapped[float | None] = mapped_column(Float)
    maximum_category: Mapped[int | None] = mapped_column(Integer)
    track_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TyphoonObservation(Base):
    __tablename__ = "typhoon_observations"
    __table_args__ = (
        UniqueConstraint("typhoon_id", "observation_time", "track_type", "row_hash", name="uq_observation_content"),
        Index("ix_observation_event_time", "typhoon_id", "observation_time"),
        Index("ix_observation_file", "source_file_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    typhoon_id: Mapped[int] = mapped_column(ForeignKey("typhoon_events.id"), index=True)
    observation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    basin: Mapped[str] = mapped_column(String(8))
    subbasin: Mapped[str | None] = mapped_column(String(8))
    nature: Mapped[str | None] = mapped_column(String(16))
    track_type: Mapped[str] = mapped_column(String(32), index=True)
    cma_wind: Mapped[float | None] = mapped_column(Float)
    cma_wind_ms: Mapped[float | None] = mapped_column(Float)
    cma_pressure: Mapped[float | None] = mapped_column(Float)
    cma_category: Mapped[int | None] = mapped_column(Integer)
    cma_lat: Mapped[float | None] = mapped_column(Float)
    cma_lon: Mapped[float | None] = mapped_column(Float)
    wmo_wind: Mapped[float | None] = mapped_column(Float)
    wmo_wind_ms: Mapped[float | None] = mapped_column(Float)
    wmo_pressure: Mapped[float | None] = mapped_column(Float)
    wmo_agency: Mapped[str | None] = mapped_column(String(64))
    usa_wind: Mapped[float | None] = mapped_column(Float)
    usa_wind_ms: Mapped[float | None] = mapped_column(Float)
    usa_pressure: Mapped[float | None] = mapped_column(Float)
    tokyo_wind: Mapped[float | None] = mapped_column(Float)
    tokyo_wind_ms: Mapped[float | None] = mapped_column(Float)
    tokyo_pressure: Mapped[float | None] = mapped_column(Float)
    wind_unit: Mapped[str] = mapped_column(String(16), default="knots")
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    iflag: Mapped[str | None] = mapped_column(String(32))
    cma_iflag: Mapped[str | None] = mapped_column(String(1), index=True)
    raw_values: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"))
    row_hash: Mapped[str] = mapped_column(String(64))
