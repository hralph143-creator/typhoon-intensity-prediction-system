"""Phase 8 dataset freezing, quality gate and event-cluster uncertainty."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.era5 import Era5File, SpatiotemporalSample, WindFieldSample


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_quality_audit(processing_version: str = "spatiotemporal-v2") -> dict:
    """Read-only scientific gate; never repairs or silently drops a row."""
    with SessionLocal() as db:
        rows = list(db.scalars(select(SpatiotemporalSample).where(
            SpatiotemporalSample.processing_version == processing_version
        ).order_by(SpatiotemporalSample.forecast_time, SpatiotemporalSample.sid)))
        file_count = db.scalar(select(func.count()).select_from(Era5File)) or 0
        field_count = db.scalar(select(func.count()).select_from(WindFieldSample).where(
            WindFieldSample.processing_version == "era5-crop-v2")) or 0

    problems = Counter()
    split_sids: dict[str, set[str]] = defaultdict(set)
    years = Counter()
    intensities = Counter()
    fingerprints = Counter()
    entries = []
    for row in rows:
        path = Path(row.local_path)
        report = row.quality_report or {}
        split_sids[row.split].add(row.sid)
        years[str(row.forecast_time.year)] += 1
        wind = float(row.target_wind)
        band = "<17.2" if wind < 17.2 else "17.2-24.4" if wind < 24.5 else "24.5-32.6" if wind < 32.7 else "32.7-41.4" if wind < 41.5 else ">=41.5"
        intensities[band] += 1
        if row.target_time - row.forecast_time != timedelta(hours=6): problems["invalid_horizon"] += 1
        if len(row.wind_field_ids or []) != 4: problems["missing_wind_fields"] += 1
        input_times = report.get("input_times") or []
        if processing_version == "spatiotemporal-v2" and len(input_times) != 4: problems["missing_input_times"] += 1
        if report.get("finite") is not True: problems["invalid_wind"] += 1
        if not path.is_file():
            problems["missing_file"] += 1
            actual_hash = None
        else:
            actual_hash = _sha256(path)
            if report.get("sha256") and actual_hash != report["sha256"]: problems["checksum_mismatch"] += 1
        fingerprint = (row.sid, row.forecast_time.isoformat(), row.processing_version)
        fingerprints[fingerprint] += 1
        entries.append({"id": row.id, "sid": row.sid, "split": row.split, "forecast_time": row.forecast_time.isoformat()+"Z", "target_time": row.target_time.isoformat()+"Z", "target_wind_ms": wind, "sha256": actual_hash})
    for count in fingerprints.values():
        if count > 1: problems["duplicate_samples"] += count - 1
    conflicts = {}
    names = ("train", "validation", "test")
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            overlap = sorted(split_sids[left] & split_sids[right])
            conflicts[f"{left}_{right}"] = overlap
            if overlap: problems["cross_split_sid"] += len(overlap)
    split_stats = {name: {"samples": sum(x["split"] == name for x in entries), "events": len(split_sids[name])} for name in names}
    sample_targets={"train":50,"validation":20,"test":20};event_targets={"train":20,"validation":5,"test":5}
    engineering_ready = all(split_stats[name]["samples"] >= sample_targets[name] and split_stats[name]["events"] >= event_targets[name] for name in names)
    passed = bool(entries) and not problems
    remaining={name:{"samples":max(0,sample_targets[name]-split_stats[name]["samples"]),"events":max(0,event_targets[name]-split_stats[name]["events"])} for name in names}
    return {"processing_version":processing_version,"passed":passed,"formal_training_allowed":passed and engineering_ready,"engineering_target_met":engineering_ready,"targets":{"samples":sample_targets,"events":event_targets},"remaining":remaining,"era5_files":file_count,"wind_fields":field_count,"samples":len(entries),"events":len(set().union(*split_sids.values())),"splits":split_stats,"years":dict(sorted(years.items())),"intensity_bands":dict(intensities),"problems":dict(problems),"sid_conflicts":conflicts,"entries":entries}


def freeze_dataset(processing_version: str = "spatiotemporal-v2") -> dict:
    audit = data_quality_audit(processing_version)
    if not audit["passed"]:
        raise ValueError(f"数据质量门禁未通过：{audit['problems']}")
    payload = {key:value for key,value in audit.items() if key != "entries"}
    payload["entries"] = audit["entries"]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    prefix="era5-phase8-final-" if audit["formal_training_allowed"] else "era5-phase8-"
    version = prefix + hashlib.sha256(canonical).hexdigest()[:16]
    payload["dataset_version"] = version
    payload["selection_frozen"] = True
    directory = settings.experiment_dir / "datasets"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**payload, "manifest_path": str(path), "manifest_sha256": _sha256(path)}


def event_cluster_bootstrap(points: list[dict], model_a: str, model_b: str | None = None, iterations: int = 2000, seed: int = 2028) -> dict:
    """Resample complete SIDs so adjacent windows are never treated as iid."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for point in points: groups[str(point["sid"])].append(point)
    sids = sorted(groups)
    if len(sids) < 5:
        return {"reliable":False,"reason":"独立测试事件少于 5 个，不报告伪精确置信区间。","event_count":len(sids)}
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(max(200, min(int(iterations), 20000))):
        chosen = rng.choice(sids, size=len(sids), replace=True)
        sample = [point for sid in chosen for point in groups[str(sid)]]
        mae_a = float(np.mean([abs(float(x[model_a]) - float(x["actual"])) for x in sample]))
        if model_b:
            mae_b = float(np.mean([abs(float(x[model_b]) - float(x["actual"])) for x in sample]))
            values.append(mae_a - mae_b)
        else: values.append(mae_a)
    low, high = np.quantile(values, [0.025, 0.975])
    return {"reliable":True,"event_count":len(sids),"iterations":len(values),"estimate":float(np.mean(values)),"ci95":[float(low),float(high)],"unit":"m/s","resampling_unit":"typhoon_event"}
