from datetime import datetime

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    database: str
    timestamp: datetime


class RuntimeInfo(BaseModel):
    software_name: str
    brand: str
    version: str
    environment: str
    python_version: str
    platform: str
    database_type: str
    database_path: str
    data_root: str


class DataSourceStatus(BaseModel):
    code: str
    name: str
    provider: str
    connected: bool
    file_count: int
    local_path: str
    status_text: str
    official_url: str

