"""明确隔离的格式测试样例，全部写入 pytest 临时目录。"""
import csv
from pathlib import Path

FIELDS = ["SID", "SEASON", "NUMBER", "BASIN", "SUBBASIN", "NAME", "ISO_TIME", "LAT", "LON", "NATURE", "WMO_WIND", "WMO_PRES", "WMO_AGENCY", "CMA_WIND", "CMA_PRES", "CMA_CAT", "CMA_LAT", "CMA_LON", "USA_WIND", "USA_PRES", "TOKYO_WIND", "TOKYO_PRES", "TRACK_TYPE", "IFLAG"]
UNITS = {"SEASON": "Year", "LAT": "degrees_north", "LON": "degrees_east", "CMA_WIND": "kts", "WMO_WIND": "kts", "USA_WIND": "kts", "TOKYO_WIND": "kts", "CMA_PRES": "mb", "WMO_PRES": "mb"}


def sample(**changes):
    row = {"SID": "TEST2014_01", "SEASON": "2014", "NUMBER": "1", "BASIN": "WP", "SUBBASIN": "MM", "NAME": "TEST ONLY", "ISO_TIME": "2014-07-01 00:00:00", "LAT": "15.1", "LON": "130.2", "NATURE": "TS", "CMA_WIND": "40", "CMA_PRES": "985", "CMA_CAT": "2", "CMA_LAT": "15.0", "CMA_LON": "130.1", "WMO_WIND": "35", "WMO_PRES": "990", "WMO_AGENCY": "tokyo", "USA_WIND": "45", "USA_PRES": "980", "TOKYO_WIND": "35", "TOKYO_PRES": "990", "TRACK_TYPE": "main", "IFLAG": "OOO____________"}
    return {**row, **changes}


def write_fixture(path: Path, rows: list[dict], *, units=True, fields=None) -> Path:
    fieldnames = fields or FIELDS
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        if units:
            writer.writerow({key: value for key, value in UNITS.items() if key in fieldnames})
        for row in rows:
            writer.writerow({key: value for key, value in row.items() if key in fieldnames})
    return path
