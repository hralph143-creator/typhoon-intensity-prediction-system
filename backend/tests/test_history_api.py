import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from backend.app.db.database import SessionLocal, init_db
from backend.app.main import app
from backend.app.models.typhoon import ImportJob, SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.services import ibtracs_importer
from backend.app.services.ibtracs_jobs import wait_for_job
from backend.tests.ibtracs_fixtures import sample, write_fixture


@pytest.fixture
def client(tmp_path, monkeypatch):
    init_db()
    with SessionLocal() as db:
        for model in (TyphoonObservation, TyphoonEvent, ImportJob, SourceFile):
            db.execute(delete(model))
        db.commit()
    monkeypatch.setattr(ibtracs_importer, "RAW_DIRECTORY", tmp_path / "raw")
    with TestClient(app) as test_client:
        yield test_client


def test_empty_and_validation_errors(client):
    assert client.get("/api/typhoons").json()["data"]["items"] == []
    assert client.get("/api/typhoons/statistics").json()["data"]["typhoon_count"] == 0
    assert client.get("/api/typhoons/999999").status_code == 404
    bad = client.get("/api/typhoons?page_size=1000")
    assert bad.status_code == 422 and bad.json()["success"] is False
    assert client.get("/api/typhoons?sort_by=invalid").status_code == 422
    assert client.get("/api/ibtracs/jobs/nonexistent").status_code == 404


def test_local_upload_query_tracks_statistics_reimport(client, tmp_path):
    path = write_fixture(tmp_path / "ibtracs.WP.list.v04r01.csv", [sample(), sample(ISO_TIME="2014-07-01 06:00:00", CMA_WIND="17"), sample(SID="2014200N15000", NAME="SECOND", ISO_TIME="2014-07-01 03:00:00", USA_WIND="70")])
    with path.open("rb") as handle:
        response = client.post("/api/ibtracs/import", files={"file": (path.name, handle, "text/csv")})
    assert response.status_code == 202
    job = wait_for_job(response.json()["data"]["id"], timeout=20)
    assert job["status"] == "succeeded", job
    assert job["valid_records"] == 3
    listed = client.get("/api/typhoons?page_size=1").json()["data"]
    assert listed["total"] == 2 and len(listed["items"]) == 1
    matched = client.get("/api/typhoons?name=SECOND&season=2014").json()["data"]
    assert matched["total"] == 1
    assert client.get("/api/typhoons?sid=2014200").json()["data"]["total"] == 1
    event_id = matched["items"][0]["id"]
    detail = client.get(f"/api/typhoons/{event_id}").json()["data"]
    assert detail["source_files"][0]["sha256"]
    track = client.get(f"/api/typhoons/{event_id}/track").json()["data"]
    assert track["items"][0]["observation_time"].endswith("Z")
    assert track["items"][0]["usa_wind_ms"] != track["items"][0]["cma_wind_ms"]
    assert client.get(f"/api/typhoons/{event_id}/intensity").json()["data"]["items"] == track["items"]
    observations = client.get(f"/api/typhoons/{event_id}/observations").json()["data"]
    assert "raw_values" in observations["items"][0]
    stats = client.get("/api/typhoons/statistics").json()["data"]
    assert stats["typhoon_count"] == 2 and stats["observation_count"] == 3
    assert stats["missing_cma_wind_count"] == 1
    assert stats["yearly"] == [{"year": 2014, "count": 2}]
    source = client.get("/api/ibtracs/status").json()["data"]
    assert source["connected"] is True
    repeat = client.post("/api/ibtracs/reimport", json={"file_id": source["imported_files"][0]["id"]})
    result = wait_for_job(repeat.json()["data"]["id"], timeout=20)
    assert result["statistics"]["idempotent"] is True
    assert client.get("/api/typhoons/statistics").json()["data"]["observation_count"] == 3


def test_upload_rejects_invalid_data(client):
    response = client.post("/api/ibtracs/import", files={"file": ("bad.csv", b"html error page\n", "text/csv")})
    assert response.status_code == 422
    response = client.post("/api/ibtracs/import", files={"file": ("bad.txt", b"x", "text/plain")})
    assert response.status_code == 422
    assert client.post("/api/ibtracs/reimport", json={"file_id": 9999}).status_code == 404


def test_conflicts_not_duplicated_in_map_but_raw_variants_visible(client, tmp_path):
    path = write_fixture(tmp_path / "conflicts.csv", [sample(), sample(LAT="16.0")])
    ibtracs_importer.import_csv(path)
    event_id = client.get("/api/typhoons").json()["data"]["items"][0]["id"]
    path_data = client.get(f"/api/typhoons/{event_id}/track").json()["data"]
    raw_data = client.get(f"/api/typhoons/{event_id}/observations").json()["data"]
    assert path_data["total"] == 1 and raw_data["total"] == 2
    assert path_data["items"][0]["latitude"] == 16


def test_cancel_nonexistent_is_not_found(client):
    assert client.post("/api/ibtracs/jobs/absent/cancel").status_code == 404
