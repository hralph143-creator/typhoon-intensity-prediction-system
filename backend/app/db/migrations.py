"""小型、版本化迁移器；升级由应用启动或 CLI 显式调用，保留旧数据表。"""
from sqlalchemy import Engine, text


def migrate(engine: Engine) -> None:
    from backend.app.models.data_source import DataSource
    from backend.app.models.system_config import SystemConfig
    from backend.app.models.typhoon import ImportJob, SourceFile, TyphoonEvent, TyphoonObservation
    from backend.app.models.ml import EvaluationResult, ModelArtifact, PredictionRecord, TrainingExperiment
    from backend.app.models.era5 import Era5DownloadJob, Era5File, SpatiotemporalSample, WindFieldSample
    from backend.app.models.report import AnalysisReport, SystemBackup

    migrations = (
        (1, "phase_one_system_metadata", (DataSource.__table__, SystemConfig.__table__)),
        (2, "ibtracs_history_and_import_jobs", (SourceFile.__table__, ImportJob.__table__, TyphoonEvent.__table__, TyphoonObservation.__table__)),
        (3, "historical_intensity_ml", (TrainingExperiment.__table__, ModelArtifact.__table__, EvaluationResult.__table__, PredictionRecord.__table__)),
        (4, "era5_spatiotemporal_samples", (Era5File.__table__, Era5DownloadJob.__table__, WindFieldSample.__table__, SpatiotemporalSample.__table__)),
        (5, "research_reports_and_backups", (AnalysisReport.__table__, SystemBackup.__table__)),
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
        for version, name, tables in migrations:
            if version not in applied:
                for table in tables:
                    table.create(bind=connection, checkfirst=True)
                connection.execute(text("INSERT INTO schema_migrations(version,name) VALUES (:version,:name)"), {"version": version, "name": name})
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(typhoon_observations)"))}
        if "iflag" not in columns:
            connection.execute(text("ALTER TABLE typhoon_observations ADD COLUMN iflag VARCHAR(32)"))
        if "cma_iflag" not in columns:
            connection.execute(text("ALTER TABLE typhoon_observations ADD COLUMN cma_iflag VARCHAR(1)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_typhoon_observations_cma_iflag ON typhoon_observations(cma_iflag)"))
        connection.execute(text("""
            UPDATE typhoon_observations
            SET iflag = json_extract(raw_values, '$.IFLAG'),
                cma_iflag = substr(json_extract(raw_values, '$.IFLAG'), 3, 1)
            WHERE iflag IS NULL OR cma_iflag IS NULL
        """))
