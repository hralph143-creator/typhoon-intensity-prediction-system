"""小型、版本化迁移器；升级由应用启动或 CLI 显式调用，保留旧数据表。"""
from sqlalchemy import Engine, text


def migrate(engine: Engine) -> None:
    from backend.app.models.data_source import DataSource
    from backend.app.models.system_config import SystemConfig
    from backend.app.models.typhoon import ImportJob, SourceFile, TyphoonEvent, TyphoonObservation

    migrations = (
        (1, "phase_one_system_metadata", (DataSource.__table__, SystemConfig.__table__)),
        (2, "ibtracs_history_and_import_jobs", (SourceFile.__table__, ImportJob.__table__, TyphoonEvent.__table__, TyphoonObservation.__table__)),
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
        for version, name, tables in migrations:
            if version not in applied:
                for table in tables:
                    table.create(bind=connection, checkfirst=True)
                connection.execute(text("INSERT INTO schema_migrations(version,name) VALUES (:version,:name)"), {"version": version, "name": name})
