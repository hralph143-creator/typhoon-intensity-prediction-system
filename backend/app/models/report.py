"""第六阶段科研报告与一致性数据库备份记录。"""
from datetime import UTC,datetime
from typing import Any

from sqlalchemy import JSON,DateTime,ForeignKey,Integer,String,Text
from sqlalchemy.orm import Mapped,mapped_column

from backend.app.db.database import Base


def utc_now():return datetime.now(UTC)


class AnalysisReport(Base):
    __tablename__="analysis_reports"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    report_type:Mapped[str]=mapped_column(String(32),index=True)
    report_title:Mapped[str]=mapped_column(String(200))
    related_typhoon_id:Mapped[int|None]=mapped_column(ForeignKey("typhoon_events.id"),index=True)
    related_experiment_id:Mapped[str|None]=mapped_column(ForeignKey("training_experiments.id"),index=True)
    source_metadata:Mapped[dict[str,Any]]=mapped_column(JSON,default=dict)
    source_snapshot_hash:Mapped[str]=mapped_column(String(64),index=True)
    report_config:Mapped[dict[str,Any]]=mapped_column(JSON,default=dict)
    report_status:Mapped[str]=mapped_column(String(24),default="queued",index=True)
    phase:Mapped[str]=mapped_column(String(48),default="queued")
    html_path:Mapped[str|None]=mapped_column(Text)
    pdf_path:Mapped[str|None]=mapped_column(Text)
    snapshot_path:Mapped[str|None]=mapped_column(Text)
    error_message:Mapped[str|None]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now,index=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))


class SystemBackup(Base):
    __tablename__="system_backups"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    backup_name:Mapped[str]=mapped_column(String(200))
    backup_path:Mapped[str]=mapped_column(Text,unique=True)
    backup_type:Mapped[str]=mapped_column(String(32),default="sqlite_metadata")
    file_size:Mapped[int]=mapped_column(Integer)
    checksum:Mapped[str]=mapped_column(String(64))
    schema_version:Mapped[int]=mapped_column(Integer)
    verification_status:Mapped[str]=mapped_column(String(24),default="verified")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now,index=True)
