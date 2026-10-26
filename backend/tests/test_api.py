from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.main import app


def test_application_health_and_database() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "healthy"
    assert payload["data"]["database"] == "connected"

    with SessionLocal() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    assert settings.database_path is not None
    assert settings.database_path.exists()


def test_system_info_is_real_runtime_data() -> None:
    with TestClient(app) as client:
        response = client.get("/api/system/info")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["software_name"] == "基于时空注意力的台风强度预测系统"
    assert data["brand"] == "云浪智析"
    assert data["python_version"]
    assert Path(data["data_root"]).name == "data"


def test_data_sources_are_not_falsely_reported_as_connected() -> None:
    with TestClient(app) as client:
        response = client.get("/api/data-sources/status")
    assert response.status_code == 200
    items = response.json()["data"]
    assert {item["code"] for item in items} == {"ibtracs", "cma", "era5"}
    assert all(item["connected"] is False for item in items)
    assert all(item["file_count"] == 0 for item in items)
    assert all(item["status_text"] == "尚未接入" for item in items)

