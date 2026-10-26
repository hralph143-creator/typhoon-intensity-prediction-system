"""第三阶段实验、模型、评估与历史回测记录。"""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TrainingExperiment(Base):
    __tablename__ = "training_experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    model_type: Mapped[str] = mapped_column(String(24), index=True)
    quality_profile: Mapped[str] = mapped_column(String(24), default="strict")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(48), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    current_epoch: Mapped[int] = mapped_column(Integer, default=0)
    max_epochs: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dataset_version: Mapped[str | None] = mapped_column(String(160))
    split_statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    training_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    device: Mapped[str | None] = mapped_column(String(32))
    seed: Mapped[int] = mapped_column(Integer, default=42)
    artifact_dir: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("training_experiments.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    model_type: Mapped[str] = mapped_column(String(24), index=True)
    model_path: Mapped[str] = mapped_column(Text)
    metadata_path: Mapped[str] = mapped_column(Text)
    dataset_version: Mapped[str] = mapped_column(String(160))
    feature_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (Index("ix_evaluation_experiment_group", "experiment_id", "split", "group_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("training_experiments.id"), index=True)
    split: Mapped[str] = mapped_column(String(24))
    group_type: Mapped[str] = mapped_column(String(32), default="overall")
    group_value: Mapped[str] = mapped_column(String(80), default="all")
    sample_count: Mapped[int] = mapped_column(Integer)
    mae: Mapped[float] = mapped_column(Float)
    rmse: Mapped[float] = mapped_column(Float)
    bias: Mapped[float] = mapped_column(Float)
    persistence_mae: Mapped[float | None] = mapped_column(Float)
    improvement_pct: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PredictionRecord(Base):
    __tablename__ = "prediction_records"
    __table_args__ = (Index("ix_prediction_model_time", "model_id", "forecast_time"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_artifacts.id"), index=True)
    typhoon_id: Mapped[int] = mapped_column(ForeignKey("typhoon_events.id"), index=True)
    sid: Mapped[str] = mapped_column(String(32))
    forecast_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_wind: Mapped[float] = mapped_column(Float)
    actual_wind: Mapped[float | None] = mapped_column(Float)
    error: Mapped[float | None] = mapped_column(Float)
    input_features: Mapped[dict[str, Any]] = mapped_column(JSON)
    quality_profile: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
