from sqlalchemy import inspect, select

from backend.app.db.database import engine, init_db
from backend.app.models.data_source import DataSource


def test_database_initialization_creates_minimal_tables() -> None:
    init_db()
    tables = set(inspect(engine).get_table_names())
    assert {"data_sources", "system_config"}.issubset(tables)
    from backend.app.db.database import SessionLocal
    with SessionLocal() as session:
        assert set(session.scalars(select(DataSource.code))) == {"ibtracs", "cma", "era5"}

