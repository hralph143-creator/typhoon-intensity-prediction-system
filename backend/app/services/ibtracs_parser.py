"""逐行解析真实 IBTrACS CSV，不填补缺测，不混合机构的风速定义。"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


KNOT_TO_MS = 0.514444
POLICY_VERSION = "wp-observations-2014-2025-cma17-censored-latest-main-v2"
REQUIRED_FIELDS = {"SID", "SEASON", "BASIN", "ISO_TIME", "LAT", "LON", "TRACK_TYPE"}
EXPECTED_FIELDS = REQUIRED_FIELDS | {"NUMBER", "SUBBASIN", "NAME", "NATURE", "WMO_WIND", "WMO_PRES", "WMO_AGENCY", "CMA_WIND", "CMA_PRES", "CMA_CAT", "CMA_LAT", "CMA_LON", "USA_WIND", "TOKYO_WIND", "IFLAG"}


class ImportCancelled(Exception):
    """用户请求取消；上层回滚本次未提交的业务数据。"""


def new_statistics() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "total_records": 0, "valid_records": 0, "skipped_records": 0, "failed_records": 0,
        "unit_rows": 0, "missing_cma_wind_records": 0, "special_cma_wind_records": 0,
        "quality_counts": {}, "skip_reasons": {}, "invalid_reasons": {},
        "selection_rule": "SEASON及UTC观测年份均为2014—2025，逐行BASIN=WP；保留全部TRACK_TYPE，默认统计仅MAIN",
        "wind_standard": "CMA 2分钟；USA 1分钟；TOKYO 10分钟；WMO按实际机构；不做机构替换",
    }


def _increment(stats: dict[str, Any], group: str, key: str) -> None:
    counts = stats.setdefault(group, {})
    counts[key] = counts.get(key, 0) + 1


def _header(reader: csv.reader) -> list[str]:
    try:
        fields = [value.strip().upper() for value in next(reader)]
    except StopIteration as exc:
        raise ValueError("CSV 文件为空") from exc
    if len(set(fields)) != len(fields):
        raise ValueError("CSV 表头包含重复字段")
    missing = REQUIRED_FIELDS - set(fields)
    if missing:
        raise ValueError("CSV 缺少必要字段：" + ", ".join(sorted(missing)))
    return fields


def _is_units(row: dict[str, str]) -> bool:
    return row.get("SEASON", "").lower() == "year" and row.get("LAT", "").lower() in {"degrees_north", "deg north", "degrees north"}


def _validate_units(units: dict[str, str]) -> None:
    for column in ("CMA_WIND", "WMO_WIND", "USA_WIND", "TOKYO_WIND"):
        if column in units and units[column].lower() not in {"kts", "kt", "kn", "knots", "knot"}:
            raise ValueError(f"{column} 单位应为节，实际为 {units[column]!r}")
    for column in ("CMA_PRES", "WMO_PRES"):
        if column in units and units[column].lower() not in {"mb", "hpa"}:
            raise ValueError(f"{column} 单位应为 mb/hPa，实际为 {units[column]!r}")


def inspect_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        fields = _header(reader)
        second = next(reader, [])
        first_row = dict(zip(fields, (value.strip() for value in second)))
        units = first_row if _is_units(first_row) else {}
        if units:
            _validate_units(units)
        match = re.search(r"v\d{2}r\d{2}", path.name, re.IGNORECASE)
        return {
            "columns": fields,
            "missing_optional_fields": sorted(EXPECTED_FIELDS - set(fields)),
            "units": units,
            "has_unit_row": bool(units),
            "version": match.group().lower() if match else "v04r01 (待核验文件名)",
        }


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _number(raw: dict[str, str], key: str, flags: list[str], *, positive: bool = False, integer: bool = False) -> float | int | None:
    value = raw.get(key, "")
    if not value or value.lower() in {"nan", "na", "null", "none", "-999", "-9999"}:
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or (positive and number < 0) or (integer and not number.is_integer()):
            raise ValueError
        return int(number) if integer else number
    except ValueError:
        flags.append(f"invalid_{key.lower()}")
        return None


def _pressure(raw: dict[str, str], key: str, flags: list[str]) -> float | None:
    value = _number(raw, key, flags, positive=True)
    if value == 0:
        flags.append(f"invalid_{key.lower()}")
        return None
    return value


def iter_csv_records(
    path: Path,
    stats: dict[str, Any] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    stats = stats if stats is not None else new_statistics()
    metadata = inspect_csv(path)
    for key, value in metadata.items():
        stats.setdefault(key, value)
    if not metadata["has_unit_row"]:
        stats["warnings"] = ["未检测到单位行，按IBTrACS v04r01列说明解释节和mb；正式科研使用前需核验来源"]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        fields = _header(reader)
        for line_number, values in enumerate(reader, start=2):
            if cancel_check and cancel_check():
                raise ImportCancelled("用户取消导入，未提交的观测已回滚")
            if not values or all(not value.strip() for value in values):
                continue
            raw = dict(zip(fields, (value.strip() for value in values)))
            if _is_units(raw):
                stats["unit_rows"] += 1
                continue
            stats["total_records"] += 1
            if stats["total_records"] % 1000 == 0 and progress_callback:
                progress_callback(stats)
            if len(values) != len(fields):
                stats["failed_records"] += 1
                _increment(stats, "invalid_reasons", "column_count")
                continue
            try:
                season = int(raw["SEASON"])
                observed = parse_utc(raw["ISO_TIME"])
            except (ValueError, KeyError):
                stats["failed_records"] += 1
                _increment(stats, "invalid_reasons", "invalid_season_or_time")
                continue
            if not (2014 <= season <= 2025 and 2014 <= observed.year <= 2025):
                stats["skipped_records"] += 1
                _increment(stats, "skip_reasons", "outside_2014_2025")
                continue
            if raw["BASIN"].upper() != "WP":
                stats["skipped_records"] += 1
                _increment(stats, "skip_reasons", "outside_wp")
                continue
            flags: list[str] = []
            latitude = _number(raw, "LAT", flags)
            longitude = _number(raw, "LON", flags)
            sid = raw.get("SID", "")
            if not sid or latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                stats["failed_records"] += 1
                _increment(stats, "invalid_reasons", "invalid_sid_or_position")
                continue
            track_type = raw["TRACK_TYPE"].upper() or "UNKNOWN"
            if track_type != "MAIN":
                flags.append("non_main_track")
            if "PROVISIONAL" in track_type:
                flags.append("provisional_track")
            if observed.hour % 6 or observed.minute or observed.second:
                flags.append("non_six_hour_time")
            interpolation_flag = raw.get("IFLAG", "")
            if len(interpolation_flag) >= 3 and interpolation_flag[2] in {"P", "I"}:
                flags.append("cma_interpolated")
            cma_wind = _number(raw, "CMA_WIND", flags, positive=True)
            cma_pressure = _pressure(raw, "CMA_PRES", flags)
            cma_wind_ms = float(cma_wind) * KNOT_TO_MS if cma_wind is not None else None
            if cma_wind == 17:
                cma_wind_ms = None
                flags.append("cma_wind_below_10")
                stats["special_cma_wind_records"] += 1
            if cma_wind_ms is None:
                stats["missing_cma_wind_records"] += 1
                if cma_wind is None:
                    flags.append("missing_cma_wind")
            if cma_pressure is None:
                flags.append("missing_cma_pressure")
            wmo_wind = _number(raw, "WMO_WIND", flags, positive=True)
            usa_wind = _number(raw, "USA_WIND", flags, positive=True)
            tokyo_wind = _number(raw, "TOKYO_WIND", flags, positive=True)
            cma_lat = _number(raw, "CMA_LAT", flags)
            cma_lon = _number(raw, "CMA_LON", flags)
            if cma_lat is not None and not -90 <= cma_lat <= 90:
                cma_lat = None
                flags.append("invalid_cma_lat")
            if cma_lon is not None and not -180 <= cma_lon <= 180:
                cma_lon = None
                flags.append("invalid_cma_lon")
            wmo_pressure = _pressure(raw, "WMO_PRES", flags)
            cma_category = _number(raw, "CMA_CAT", flags, integer=True)
            if cma_category is not None and cma_category not in {0, 1, 2, 3, 4, 5, 6, 9}:
                cma_category = None
                flags.append("invalid_cma_cat")
            record = {
                "sid": sid, "season": season,
                "number": _number(raw, "NUMBER", flags, positive=True, integer=True),
                "name": raw.get("NAME", "") or "未命名",
                "observation_time": observed, "latitude": latitude, "longitude": longitude,
                "basin": "WP", "subbasin": raw.get("SUBBASIN") or None,
                "nature": raw.get("NATURE") or None, "track_type": track_type,
                "cma_wind": cma_wind, "cma_wind_ms": cma_wind_ms, "cma_pressure": cma_pressure,
                "cma_category": cma_category,
                "cma_lat": cma_lat, "cma_lon": cma_lon,
                "wmo_wind": wmo_wind, "wmo_wind_ms": wmo_wind * KNOT_TO_MS if wmo_wind is not None else None,
                "wmo_pressure": wmo_pressure, "wmo_agency": raw.get("WMO_AGENCY") or None,
                "usa_wind": usa_wind, "usa_wind_ms": usa_wind * KNOT_TO_MS if usa_wind is not None else None,
                "usa_pressure": _pressure(raw, "USA_PRES", flags),
                "tokyo_wind": tokyo_wind, "tokyo_wind_ms": tokyo_wind * KNOT_TO_MS if tokyo_wind is not None else None,
                "tokyo_pressure": _pressure(raw, "TOKYO_PRES", flags),
                "wind_unit": "knots", "quality_flags": flags,
                "raw_values": raw,
                "row_hash": hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            }
            for flag in flags:
                _increment(stats, "quality_counts", flag)
            stats["valid_records"] += 1
            yield record
