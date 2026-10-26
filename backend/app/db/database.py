from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


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
    Base.metadata.create_all(bind=engine)
    sources = (
        DataSource(code="ibtracs", name="IBTrACS 最佳路径数据", provider="NOAA NCEI", official_url="https://www.ncei.noaa.gov/products/international-best-track-archive"),
        DataSource(code="cma", name="CMA 最佳路径数据", provider="中国气象局", official_url="https://tcdata.typhoon.org.cn/zjljsjj.html"),
        DataSource(code="era5", name="ERA5 近海面风场", provider="Copernicus CDS", official_url="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"),
    )
    with SessionLocal() as session:
        for source in sources:
            session.merge(source)
        session.commit()

