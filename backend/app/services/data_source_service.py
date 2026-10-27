from dataclasses import dataclass
from pathlib import Path

from backend.app.core.config import PROJECT_ROOT
from backend.app.schemas.system import DataSourceStatus
from backend.app.db.database import SessionLocal
from backend.app.models.typhoon import SourceFile, TyphoonObservation
from backend.app.models.era5 import Era5File
from backend.app.models.typhoon import TyphoonEvent
from sqlalchemy import select, func


@dataclass(frozen=True)
class SourceDefinition:
    code: str
    name: str
    provider: str
    folder: str
    patterns: tuple[str, ...]
    url: str


SOURCES = (
    SourceDefinition(
        "ibtracs", "IBTrACS 最佳路径数据", "NOAA NCEI", "ibtracs", ("*.csv",),
        "https://www.ncei.noaa.gov/products/international-best-track-archive",
    ),
    SourceDefinition(
        "cma", "CMA 最佳路径数据", "中国气象局", "cma", ("CH*BST.txt", "*.txt"),
        "https://tcdata.typhoon.org.cn/zjljsjj.html",
    ),
    SourceDefinition(
        "era5", "ERA5 近海面风场", "ECMWF / Copernicus C3S", "era5", ("*.nc", "*.nc4", "*.grib"),
        "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels",
    ),
)


def get_data_source_statuses() -> list[DataSourceStatus]:
    raw_root = PROJECT_ROOT / "data" / "raw"
    statuses: list[DataSourceStatus] = []
    for source in SOURCES:
        source_path = raw_root / source.folder
        source_path.mkdir(parents=True, exist_ok=True)
        files: set[Path] = set()
        for pattern in source.patterns:
            files.update(path for path in source_path.glob(pattern) if path.is_file())
        connected = bool(files)
        imported = False
        if source.code in {"ibtracs", "cma"}:
            with SessionLocal() as db:
                imported = bool(db.scalar(select(func.count()).select_from(TyphoonObservation).join(TyphoonEvent).where(TyphoonEvent.source == source.code)))
            connected = imported
        elif source.code == "era5":
            with SessionLocal() as db:
                imported = bool(db.scalar(select(func.count()).select_from(Era5File).where(Era5File.status == "valid")))
            connected = imported
        statuses.append(
            DataSourceStatus(
                code=source.code,
                name=source.name,
                provider=source.provider,
                connected=connected,
                file_count=len(files),
                local_path=str(source_path),
                status_text="已导入真实数据" if imported else "已检测到本地文件，尚未导入" if files else "尚未接入",
                official_url=source.url,
            )
        )
    return statuses

