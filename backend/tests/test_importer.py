from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.migrations import migrate
from backend.app.models.typhoon import SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.services import ibtracs_importer as importer
from backend.app.services.ibtracs_parser import ImportCancelled
from backend.tests.ibtracs_fixtures import sample, write_fixture


@pytest.fixture
def isolated_importer(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "test.db").as_posix())
    migrate(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(importer, "SessionLocal", sessions)
    monkeypatch.setattr(importer, "RAW_DIRECTORY", tmp_path / "managed-raw")
    yield sessions
    engine.dispose()


def test_import_groups_sorts_preserves_tracks_and_is_idempotent(tmp_path, isolated_importer):
    first = sample(ISO_TIME="2014-07-01 06:00:00", CMA_WIND="50")
    earlier = sample(ISO_TIME="2014-07-01 00:00:00")
    spur = sample(ISO_TIME="2014-07-01 06:00:00", TRACK_TYPE="spur", CMA_WIND="100")
    path = write_fixture(tmp_path / "ibtracs.WP.list.v04r01.csv", [first, earlier, earlier, spur])
    report = importer.import_csv(path, source_url="https://www.ncei.noaa.gov/test.csv")
    assert report["total_records"] == 4
    assert report["inserted_records"] == 3
    assert report["duplicate_records"] == 1
    assert report["typhoon_count"] == 1
    with isolated_importer() as session:
        event = session.scalar(select(TyphoonEvent))
        assert event.observation_count == 3
        assert event.first_observation.hour == 0
        assert event.last_observation.hour == 6
        assert event.maximum_wind == pytest.approx(50 * 0.514444)
        assert set(event.track_types) == {"MAIN", "SPUR"}
        source = session.scalar(select(SourceFile))
        assert source.version == "v04r01"
        assert Path(source.local_path).read_bytes() == path.read_bytes()
        assert source.sha256 == report["sha256"]
    repeat = importer.import_csv(path)
    assert repeat["idempotent"] is True
    with isolated_importer() as session:
        assert session.scalar(select(func.count()).select_from(TyphoonObservation)) == 3
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 1


def test_conflicting_observations_are_retained_and_marked(tmp_path, isolated_importer):
    path = write_fixture(tmp_path / "conflict.csv", [sample(), sample(LAT="16.0")])
    report = importer.import_csv(path)
    assert report["conflicting_records"] == 1
    with isolated_importer() as session:
        records = list(session.scalars(select(TyphoonObservation)))
        assert len(records) == 2
        assert all("conflicting_observation" in row.quality_flags for row in records)


def test_identical_observation_from_different_file_not_duplicated(tmp_path, isolated_importer):
    importer.import_csv(write_fixture(tmp_path / "one.csv", [sample()]))
    report = importer.import_csv(write_fixture(tmp_path / "two.csv", [sample(), sample(ISO_TIME="2014-07-01 06:00:00")]))
    assert report["duplicate_records"] == 1
    assert report["inserted_records"] == 1
    with isolated_importer() as session:
        assert session.scalar(select(func.count()).select_from(TyphoonObservation)) == 2
        assert session.scalar(select(func.count()).select_from(SourceFile)) == 2


def test_cancel_rolls_back_business_records_but_retains_original(tmp_path, isolated_importer, monkeypatch):
    monkeypatch.setattr(importer, "BATCH_SIZE", 1)
    cancelled = False
    def progress(_):
        nonlocal cancelled
        cancelled = True
    path = write_fixture(tmp_path / "cancel.csv", [sample(), sample(ISO_TIME="2014-07-01 06:00:00")])
    with pytest.raises(ImportCancelled):
        importer.import_csv(path, cancel_check=lambda: cancelled, progress_callback=progress)
    with isolated_importer() as session:
        assert session.scalar(select(func.count()).select_from(TyphoonObservation)) == 0
        assert session.scalar(select(func.count()).select_from(TyphoonEvent)) == 0
        source = session.scalar(select(SourceFile))
        assert source.status == "failed"
        assert Path(source.local_path).exists()


def test_managed_original_is_not_duplicated(tmp_path, isolated_importer):
    importer.RAW_DIRECTORY.mkdir()
    path = write_fixture(importer.RAW_DIRECTORY / "ibtracs.WP.list.v04r01.csv", [sample()])
    importer.import_csv(path)
    assert len(list(importer.RAW_DIRECTORY.glob("*.csv"))) == 1
    with isolated_importer() as session:
        source = session.scalar(select(SourceFile))
        assert Path(source.local_path) == path.resolve()


def test_migrations_are_versioned_and_repeatable(tmp_path):
    from sqlalchemy import inspect, text
    engine = create_engine("sqlite:///" + (tmp_path / "migration.db").as_posix())
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert list(connection.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars()) == [1, 2, 3]
    assert {"data_sources", "system_config", "source_files", "data_import_jobs", "typhoon_events", "typhoon_observations", "training_experiments", "model_artifacts", "evaluation_results", "prediction_records"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_event_summary_uses_same_latest_conflict_as_map(tmp_path, isolated_importer):
    path = write_fixture(tmp_path / "conflicts.csv", [sample(CMA_WIND="100", CMA_PRES="920", CMA_CAT="6"), sample(CMA_WIND="50", CMA_PRES="980", CMA_CAT="2")])
    importer.import_csv(path)
    with isolated_importer() as session:
        event = session.scalar(select(TyphoonEvent))
        assert event.maximum_wind == pytest.approx(50 * 0.514444)
        assert event.minimum_pressure == 980
        assert event.maximum_category == 2
        assert event.observation_count == 2


def test_upload_original_filename_preserves_version(tmp_path, isolated_importer):
    path = write_fixture(tmp_path / "uuid-upload.csv", [sample()])
    importer.import_csv(path, original_filename="ibtracs.WP.list.v04r01.csv")
    with isolated_importer() as session:
        source = session.scalar(select(SourceFile))
        assert source.version == "v04r01"
        assert source.original_filename == "ibtracs.WP.list.v04r01.csv"


def test_non_main_event_keeps_full_lifecycle_without_main_extrema(tmp_path, isolated_importer):
    path = write_fixture(tmp_path / "provisional.csv", [sample(TRACK_TYPE="US-PROVISIONAL", ISO_TIME="2014-07-01 06:00:00"), sample(TRACK_TYPE="US-PROVISIONAL", ISO_TIME="2014-07-01 00:00:00")])
    importer.import_csv(path)
    with isolated_importer() as session:
        event = session.scalar(select(TyphoonEvent))
        assert event.first_observation.hour == 0
        assert event.last_observation.hour == 6
        assert event.maximum_wind is None
        assert event.minimum_pressure is None
        assert event.maximum_category is None
