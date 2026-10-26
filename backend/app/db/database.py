from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
database_url = settings.database_url
if settings.database_path:
    database_url = "sqlite:///" + settings.database_path.as_posix()
engine = create_engine(database_url, connect_args={**connect_args, **({"timeout": 30} if database_url.startswith("sqlite") else {})}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


if database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend.app.models import data_source, system_config  # noqa: F401
    from backend.app.models.data_source import DataSource

    if settings.database_path:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    from backend.app.db.migrations import migrate
    migrate(engine)
    sources = (
        DataSource(code="ibtracs", name="IBTrACS 最佳路径数据", provider="NOAA NCEI", official_url="https://www.ncei.noaa.gov/products/international-best-track-archive"),
        DataSource(code="cma", name="CMA 最佳路径数据", provider="中国气象局", official_url="https://tcdata.typhoon.org.cn/zjljsjj.html"),
        DataSource(code="era5", name="ERA5 近海面风场", provider="Copernicus CDS", official_url="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"),
    )
    with SessionLocal() as session:
        for source in sources:
            session.merge(source)
        session.commit()

