from datetime import UTC

import pytest

from backend.app.services.ibtracs_parser import KNOT_TO_MS, inspect_csv, iter_csv_records, new_statistics, parse_utc
from backend.tests.ibtracs_fixtures import FIELDS, sample, write_fixture


def test_header_units_and_optional_difference(tmp_path):
    path = write_fixture(tmp_path / "ibtracs.WP.list.v04r01.csv", [sample()], fields=[key for key in FIELDS if key != "CMA_CAT"])
    metadata = inspect_csv(path)
    assert metadata["has_unit_row"] is True
    assert metadata["units"]["CMA_WIND"] == "kts"
    assert metadata["missing_optional_fields"] == ["CMA_CAT"]
    assert metadata["version"] == "v04r01"
    stats = new_statistics()
    assert len(list(iter_csv_records(path, stats))) == 1
    assert stats["total_records"] == 1
    assert stats["unit_rows"] == 1


def test_agency_wind_units_are_separate_and_missing_stays_missing(tmp_path):
    path = write_fixture(tmp_path / "sample.csv", [sample(CMA_WIND=" ", CMA_PRES=" ")])
    item = next(iter_csv_records(path))
    assert item["cma_wind_ms"] is None
    assert item["cma_pressure"] is None
    assert item["usa_wind_ms"] == pytest.approx(45 * KNOT_TO_MS)
    assert item["tokyo_wind_ms"] == pytest.approx(35 * KNOT_TO_MS)
    assert item["wmo_agency"] == "tokyo"
    assert item["raw_values"]["CMA_WIND"] == ""
    assert "missing_cma_wind" in item["quality_flags"]


def test_cma_special_17_knots_is_censored_not_exact_speed(tmp_path):
    path = write_fixture(tmp_path / "sample.csv", [sample(CMA_WIND="17")])
    stats = new_statistics()
    item = next(iter_csv_records(path, stats))
    assert item["cma_wind"] == 17
    assert item["cma_wind_ms"] is None
    assert "cma_wind_below_10" in item["quality_flags"]
    assert stats["special_cma_wind_records"] == 1


def test_utc_and_non_six_hour_times_are_preserved(tmp_path):
    path = write_fixture(tmp_path / "sample.csv", [sample(ISO_TIME="2014-07-01 03:00:00", IFLAG="OOP____________")])
    item = next(iter_csv_records(path))
    assert item["observation_time"].tzinfo == UTC
    assert item["observation_time"].hour == 3
    assert {"non_six_hour_time", "cma_interpolated"} <= set(item["quality_flags"])
    assert parse_utc("2014-07-01T08:00:00+08:00").hour == 0


@pytest.mark.parametrize("changes", [{"LAT": "91"}, {"LON": "181"}, {"ISO_TIME": "bad"}, {"SID": ""}])
def test_invalid_position_or_time_is_rejected(tmp_path, changes):
    stats = new_statistics()
    path = write_fixture(tmp_path / "sample.csv", [sample(**changes)])
    assert list(iter_csv_records(path, stats)) == []
    assert stats["failed_records"] == 1


def test_negative_values_preserved_raw_but_not_normalized(tmp_path):
    item = next(iter_csv_records(write_fixture(tmp_path / "sample.csv", [sample(CMA_WIND="-5", CMA_PRES="-10")])) )
    assert item["cma_wind"] is None
    assert item["cma_pressure"] is None
    assert item["raw_values"]["CMA_WIND"] == "-5"
    assert "invalid_cma_wind" in item["quality_flags"]


def test_research_period_and_per_row_basin_filter(tmp_path):
    rows = [sample(), sample(BASIN="EP"), sample(SEASON="2026", ISO_TIME="2026-01-01 00:00:00"), sample(SEASON="2025", ISO_TIME="2026-01-01 00:00:00")]
    stats = new_statistics()
    items = list(iter_csv_records(write_fixture(tmp_path / "sample.csv", rows), stats))
    assert len(items) == 1
    assert stats["skipped_records"] == 3
    assert stats["skip_reasons"] == {"outside_wp": 1, "outside_2014_2025": 2}


def test_missing_required_header_and_wrong_unit_are_errors(tmp_path):
    path = write_fixture(tmp_path / "bad.csv", [sample()], fields=[key for key in FIELDS if key != "SID"])
    with pytest.raises(ValueError, match="SID"):
        inspect_csv(path)
    unit_path = write_fixture(tmp_path / "wrong.csv", [sample()])
    content = unit_path.read_text(encoding="utf-8-sig").replace("kts", "m/s")
    unit_path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="单位"):
        inspect_csv(unit_path)


def test_no_unit_row_does_not_skip_first_observation(tmp_path):
    path = write_fixture(tmp_path / "no-units.csv", [sample()], units=False)
    stats = new_statistics()
    assert len(list(iter_csv_records(path, stats))) == 1
    assert stats["unit_rows"] == 0
    assert stats["warnings"]
