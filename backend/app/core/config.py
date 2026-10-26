from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode
from typing import Annotated


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "基于时空注意力的台风强度预测系统"
    app_brand: str = "云浪智析"
    app_version: str = "0.2.0"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./data/system.db"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    log_level: str = "INFO"
    ibtracs_url: str = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.WP.list.v04r01.csv"
    upload_max_bytes: int = 512 * 1024 * 1024
    download_timeout: float = 45.0
    download_retries: int = 3

    @property
    def raw_data_dir(self) -> Path:
        return PROJECT_ROOT / "data" / "raw" / "ibtracs"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def database_path(self) -> Path | None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw_path = Path(self.database_url.removeprefix(prefix))
        return raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

