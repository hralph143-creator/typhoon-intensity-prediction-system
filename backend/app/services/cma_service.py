"""独立 CMA 最佳路径文本文件校验与入库。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import delete, func, select

from backend.app.core.config import PROJECT_ROOT
from backend.app.db.database import SessionLocal
from backend.app.models.typhoon import SourceFile, TyphoonEvent, TyphoonObservation


RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "cma"
OFFICIAL_URL = "https://tcdata.typhoon.org.cn/zjljsjj.html"
POLICY_VERSION = "cma-best-track-2014-2025-v1"
HEADER_RE = re.compile(r"^66666\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d)\s+(\d)\s+(.*?)\s+(\d{8})\s*$")


def _record_hash(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def archive_url(year: int) -> str:
    if year >= 2023:
        return f"https://zenodo.org/records/19561118/files/CH{year}BST.txt?download=1"
    return f"https://raw.githubusercontent.com/lzcapp/TropicalCyclone-Data/main/CMABST/CH{year}BST.txt"


def parse_cma_file(path: Path) -> Iterator[dict]:
    """Parse one official CHYYYYBST text file without inventing missing values."""
    year_match = re.fullmatch(r"CH(\d{4})BST\.txt", path.name, re.IGNORECASE)
    if not year_match:
        raise ValueError(f"不符合 CMA 年度文件命名规则：{path.name}")
    file_year = int(year_match.group(1))
    current: dict | None = None
    remaining = 0
    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.rstrip("\r\n")
            if not line.strip():
                continue
            if line.startswith("66666"):
                if remaining:
                    raise ValueError(f"{path.name}:{line_number} 上一台风尚缺 {remaining} 条记录")
                match = HEADER_RE.match(line)
                if not match:
                    raise ValueError(f"{path.name}:{line_number} 头记录格式错误")
                international_id, count, serial, chinese_id, end_flag, interval, name, revision = match.groups()
                current = {
                    "season": file_year,
                    "sid": f"CMA-{file_year}-{serial}",
                    "international_id": international_id,
                    "serial": serial,
                    "chinese_id": chinese_id,
                    "number": int(chinese_id[-2:]) if chinese_id.isdigit() and chinese_id != "0000" else None,
                    "name": name.strip() or "未命名",
                    "end_flag": int(end_flag),
                    "interval_hours": int(interval),
                    "revision": revision,
                    "observations": [],
                }
                remaining = int(count)
                continue
            if current is None or remaining <= 0:
                raise ValueError(f"{path.name}:{line_number} 数据记录缺少对应头记录")
            fields = line.split()
            if len(fields) < 6:
                raise ValueError(f"{path.name}:{line_number} 数据记录字段不足")
            try:
                observed = datetime.strptime(fields[0], "%Y%m%d%H").replace(tzinfo=UTC)
                category = int(fields[1])
                latitude = int(fields[2]) / 10
                longitude = int(fields[3]) / 10
                pressure_raw = int(fields[4])
                wind_raw = int(fields[5])
                outer_wind = int(fields[6]) if len(fields) > 6 else None
            except ValueError as exc:
                raise ValueError(f"{path.name}:{line_number} 含无效数值") from exc
            if observed.year not in {file_year - 1, file_year, file_year + 1} or category not in {0, 1, 2, 3, 4, 5, 6, 9} or not -90 <= latitude <= 90 or not 0 <= longitude <= 360:
                raise ValueError(f"{path.name}:{line_number} 时间、类别或经纬度越界")
            flags = ["cma_official_direct"]
            wind_ms = None if wind_raw in {0, 9} else float(wind_raw)
            if wind_raw == 0:
                flags.append("missing_cma_wind")
            elif wind_raw == 9:
                flags.append("cma_wind_below_10")
            if observed.hour % 6:
                flags.append("cma_three_hour_landfall_record")
            pressure = float(pressure_raw) if pressure_raw > 0 else None
            if pressure is None:
                flags.append("missing_cma_pressure")
            raw = {
                "time": fields[0], "category": category, "latitude_tenths": int(fields[2]),
                "longitude_tenths": int(fields[3]), "pressure_hpa": pressure_raw,
                "wind_ms": wind_raw, "outer_wind_ms": outer_wind,
            }
            current["observations"].append({
                "observation_time": observed, "latitude": latitude,
                "longitude": longitude if longitude <= 180 else longitude - 360,
                "category": category, "pressure": pressure, "wind_ms": wind_ms,
                "quality_flags": flags, "raw_values": raw, "row_hash": _record_hash(raw),
            })
            remaining -= 1
            if remaining == 0:
                yield current
                current = None
    if remaining:
        raise ValueError(f"{path.name} 文件结尾仍缺 {remaining} 条记录")


def inspect_file(path: Path) -> dict:
    events = list(parse_cma_file(path))
    observations = [item for event in events for item in event["observations"]]
    if not events or not observations:
        raise ValueError(f"{path.name} 没有可用台风记录")
    return {
        "event_count": len(events), "observation_count": len(observations),
        "year": events[0]["season"], "first_time": min(x["observation_time"] for x in observations).isoformat(),
        "last_time": max(x["observation_time"] for x in observations).isoformat(),
        "revision_dates": sorted({event["revision"] for event in events}),
    }


def import_file(path: Path) -> dict:
    path = path.resolve()
    events = list(parse_cma_file(path))
    report = inspect_file(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        source_file = db.scalar(select(SourceFile).where(SourceFile.sha256 == digest))
        if source_file and source_file.status == "imported":
            source_file.source_url = archive_url(report["year"])
            source_file.statistics = {**(source_file.statistics or report), "official_url": OFFICIAL_URL, "archive_url": archive_url(report["year"])}
            return {**(source_file.statistics or report), "file_id": source_file.id, "reused": True}
        if source_file is None:
            source_file = SourceFile(
                source="cma", original_filename=path.name, local_path=str(path), sha256=digest,
                file_size=path.stat().st_size, version="CMA-2026-04", source_url=archive_url(report["year"]),
            )
            db.add(source_file)
            db.flush()
        prior_events = list(db.scalars(select(TyphoonEvent).where(
            TyphoonEvent.source == "cma", TyphoonEvent.season == report["year"]
        )))
        if prior_events:
            prior_ids = [event.id for event in prior_events]
            db.execute(delete(TyphoonObservation).where(TyphoonObservation.typhoon_id.in_(prior_ids)))
            db.execute(delete(TyphoonEvent).where(TyphoonEvent.id.in_(prior_ids)))
        for previous_file in db.scalars(select(SourceFile).where(
            SourceFile.source == "cma", SourceFile.id != source_file.id,
        )):
            if (previous_file.statistics or {}).get("year") == report["year"]:
                previous_file.status = "superseded"
        for parsed in events:
            rows = parsed["observations"]
            valid_winds = [row["wind_ms"] for row in rows if row["wind_ms"] is not None]
            valid_pressures = [row["pressure"] for row in rows if row["pressure"] is not None]
            event = TyphoonEvent(
                source="cma", sid=parsed["sid"], season=parsed["season"], number=parsed["number"],
                name=parsed["name"], first_observation=rows[0]["observation_time"],
                last_observation=rows[-1]["observation_time"], observation_count=len(rows),
                maximum_wind=max(valid_winds) if valid_winds else None,
                minimum_pressure=min(valid_pressures) if valid_pressures else None,
                maximum_category=max(row["category"] for row in rows), track_types=["MAIN"],
            )
            db.add(event)
            db.flush()
            for row in rows:
                db.add(TyphoonObservation(
                    typhoon_id=event.id, observation_time=row["observation_time"],
                    latitude=row["latitude"], longitude=row["longitude"], basin="WP", subbasin=None,
                    nature=None, track_type="MAIN", cma_wind=row["wind_ms"], cma_wind_ms=row["wind_ms"],
                    cma_pressure=row["pressure"], cma_category=row["category"],
                    cma_lat=row["latitude"], cma_lon=row["longitude"],
                    wmo_wind=None, wmo_wind_ms=None, wmo_pressure=None, wmo_agency=None,
                    usa_wind=None, usa_wind_ms=None, usa_pressure=None,
                    tokyo_wind=None, tokyo_wind_ms=None, tokyo_pressure=None,
                    wind_unit="m/s", quality_flags=row["quality_flags"], iflag=None, cma_iflag="O",
                    raw_values={**row["raw_values"], "header": {key: parsed[key] for key in ("international_id", "serial", "chinese_id", "end_flag", "interval_hours", "revision")}},
                    source_file_id=source_file.id, row_hash=row["row_hash"],
                ))
        source_file.imported_at = now
        source_file.status = "imported"
        source_file.statistics = {**report, "policy_version": POLICY_VERSION, "sha256": digest,
            "official_url": OFFICIAL_URL, "archive_url": archive_url(report["year"])}
        db.flush()
        file_id = source_file.id
    return {**report, "file_id": file_id, "sha256": digest, "reused": False}


def import_local_files(start_year: int = 2014, end_year: int = 2025) -> dict:
    reports = []
    for year in range(start_year, end_year + 1):
        path = RAW_DIRECTORY / f"CH{year}BST.txt"
        if not path.is_file():
            raise FileNotFoundError(f"缺少 CMA 年度文件：{path.name}")
        reports.append(import_file(path))
    return {
        "files": len(reports), "event_count": sum(item["event_count"] for item in reports),
        "observation_count": sum(item["observation_count"] for item in reports),
        "years": list(range(start_year, end_year + 1)), "reports": reports,
    }


def status() -> dict:
    with SessionLocal() as db:
        files = db.scalar(select(func.count()).select_from(SourceFile).where(SourceFile.source == "cma", SourceFile.status == "imported")) or 0
        events = db.scalar(select(func.count()).select_from(TyphoonEvent).where(TyphoonEvent.source == "cma")) or 0
        observations = db.scalar(select(func.count()).select_from(TyphoonObservation).join(TyphoonEvent).where(TyphoonEvent.source == "cma")) or 0
        last_import = db.scalar(select(func.max(SourceFile.imported_at)).where(SourceFile.source == "cma", SourceFile.status == "imported"))
    return {
        "source": "cma", "official_url": OFFICIAL_URL, "connected": observations > 0,
        "file_count": files, "typhoon_count": events, "observation_count": observations,
        "last_import_at": last_import.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if last_import else None,
        "years": [2014, 2025] if observations else [], "wind_standard": "CMA 2分钟平均最大风速（m/s）",
    }
