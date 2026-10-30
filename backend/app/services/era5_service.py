"""ERA5 接入、NetCDF 校验、风场裁剪与四时次样本构建。"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import xarray as xr
from sqlalchemy import func, select

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.era5 import Era5DownloadJob, Era5File, Era5SampleBatch, SpatiotemporalSample, WindFieldSample
from backend.app.models.typhoon import TyphoonEvent, TyphoonObservation
from backend.app.services.ml_dataset import build_samples, dataset_version, split_statistics
from backend.app.services.era5_sources import ADAPTERS, choose_source, load_source_state, run_read_worker, save_source_state

DATASET = "reanalysis-era5-single-levels"
OFFICIAL_URL = "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"
SETUP_URL = "https://cds.climate.copernicus.eu/how-to-api"
PUBLIC_ARCO_URL = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
PROCESSING_VERSION = "spatiotemporal-v2"
CROP_VERSION = "era5-crop-v2"
# The surface U10/V10 arrays use one 721x1440 float32 global field per hour.
# This is theoretical uncompressed size, never reported as measured transfer.
ARCO_CHUNK_ESTIMATE_BYTES = 721 * 1440 * 4
OFFSETS = (18, 12, 6, 0)
ACTIVE_JOB_STATUSES = {"queued", "submitting", "processing", "downloading", "validating"}
_executor = ThreadPoolExecutor(max_workers=settings.era5_max_workers, thread_name_prefix="era5")
_signals: dict[str, threading.Event] = {}
_batch_signals: dict[str, threading.Event] = {}


def _open_loaded(path: Path) -> xr.Dataset:
    """Avoid native-library path encoding problems by reading through memory."""
    payload = path.read_bytes()
    for engine in ("h5netcdf", "scipy"):
        try:
            with xr.open_dataset(io.BytesIO(payload), engine=engine) as dataset:
                return dataset.load()
        except Exception:
            continue
    raise ValueError("无法识别 NetCDF3/NetCDF4 文件")


def _iso(value) -> str:
    if isinstance(value, datetime):
        text=value.isoformat()
        return text.replace("+00:00","Z") if value.tzinfo else text+"Z"
    return value.isoformat() if hasattr(value,"isoformat") else str(value)


def credential_status() -> dict:
    config = Path.home() / ".cdsapirc"
    exists = config.is_file()
    text = config.read_text("utf-8", errors="ignore") if exists else ""
    has_url = any(line.strip().startswith("url:") and line.split(":", 1)[1].strip() for line in text.splitlines())
    has_key = any(line.strip().startswith("key:") and line.split(":", 1)[1].strip() for line in text.splitlines())
    configured = bool((has_url and has_key) or (os.getenv("CDSAPI_URL") and os.getenv("CDSAPI_KEY")))
    return {
        "configured": configured, "config_file_exists": exists, "has_url": bool(has_url), "has_key": bool(has_key),
        "dataset_terms_must_be_accepted": True, "setup_url": SETUP_URL, "dataset_url": OFFICIAL_URL,
        "message": "CDS API 已配置；仍需在数据集页面接受许可。" if configured else "未发现 CDS API 凭据，请按官方指引配置 .cdsapirc。",
    }


def connection_test() -> dict:
    status = credential_status()
    if not status["configured"]:
        return {**status, "reachable": False, "reason": "credentials_missing"}
    try:
        import cdsapi
        client = cdsapi.Client(quiet=True)
        return {**status, "reachable": True, "reason": None, "client": client.__class__.__name__}
    except Exception as exc:
        return {**status, "reachable": False, "reason": type(exc).__name__, "message": f"客户端初始化失败：{exc}"}


def _request_hash(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bounds(lat: float, lon: float, margin: float = 4.0) -> list[list[float]]:
    north, south = min(90.0, lat + margin), max(-90.0, lat - margin)
    west, east = lon - margin, lon + margin
    if west < -180:
        return [[north, west + 360, south, 180], [north, -180, south, east]]
    if east > 180:
        return [[north, west, south, 180], [north, -180, south, east - 360]]
    return [[north, west, south, east]]


def _request(moment: datetime, area: list[float]) -> dict:
    return {
        "product_type": ["reanalysis"],
        "variable": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
        "year": [f"{moment.year:04d}"], "month": [f"{moment.month:02d}"], "day": [f"{moment.day:02d}"],
        "time": [f"{moment.hour:02d}:00"], "data_format": "netcdf", "download_format": "unarchived",
        "area": [round(x, 2) for x in area],
    }


def preview_plans(limit: int = 3) -> list[dict]:
    samples = build_samples("strict")
    selected = []
    seen_splits = set()
    for sample in reversed(samples):
        if sample.split in seen_splits:
            continue
        selected.append(sample); seen_splits.add(sample.split)
        if len(selected) >= limit:
            break
    plans = []
    with SessionLocal() as db:
        for sample in selected:
            observations = list(db.scalars(select(TyphoonObservation).where(
                TyphoonObservation.typhoon_id == sample.typhoon_id,
                TyphoonObservation.observation_time.in_([sample.forecast_time - timedelta(hours=h) for h in OFFSETS]),
                TyphoonObservation.track_type == "MAIN",
            ).order_by(TyphoonObservation.observation_time)))
            by_time = {row.observation_time: row for row in observations}
            requests = []
            for hours in OFFSETS:
                moment = sample.forecast_time - timedelta(hours=hours)
                row = by_time.get(moment)
                if not row: continue
                lat, lon = row.cma_lat or row.latitude, row.cma_lon or row.longitude
                for part, area in enumerate(_bounds(lat, lon), 1):
                    request = _request(moment, area)
                    requests.append({"time": _iso(moment), "center": [lat, lon], "part": part, "request_hash": _request_hash(request), "request": request})
            plans.append({"sid": sample.sid, "typhoon_id": sample.typhoon_id, "split": sample.split, "forecast_time": _iso(sample.forecast_time), "target_time": _iso(sample.target_time), "requests": requests})
    return plans


def _names(ds: xr.Dataset):
    def pick(options, collection):
        return next((name for name in options if name in collection), None)
    return (
        pick(("u10", "10m_u_component_of_wind"), ds.data_vars),
        pick(("v10", "10m_v_component_of_wind"), ds.data_vars),
        pick(("latitude", "lat"), ds.coords), pick(("longitude", "lon"), ds.coords),
        pick(("valid_time", "time"), ds.coords),
    )


def inspect_netcdf(path: Path) -> dict:
    try:
        with _open_loaded(path) as ds:
            u, v, lat, lon, time = _names(ds)
            missing = [label for label, value in (("u10", u), ("v10", v), ("latitude", lat), ("longitude", lon), ("time", time)) if not value]
            if missing: raise ValueError("缺少字段：" + ", ".join(missing))
            ua, va = ds[u], ds[v]
            units = {"u10": str(ua.attrs.get("units", "")), "v10": str(va.attrs.get("units", ""))}
            if any(unit and unit not in {"m s**-1", "m s-1", "m/s", "m s^-1"} for unit in units.values()):
                raise ValueError(f"风速单位不是 m/s：{units}")
            latv, lonv = np.asarray(ds[lat].values, float), np.asarray(ds[lon].values, float)
            times = np.atleast_1d(ds[time].values)
            sample_u, sample_v = np.asarray(ua.values), np.asarray(va.values)
            finite = np.isfinite(sample_u) & np.isfinite(sample_v)
            speed = np.sqrt(sample_u[finite] ** 2 + sample_v[finite] ** 2) if finite.any() else np.array([])
            return {
                "valid": bool(finite.any()), "variables": [u, v], "units": units,
                "dimensions": {key: int(value) for key, value in ds.sizes.items()},
                "time_start": _iso(np.datetime_as_string(times.min(), unit="s")), "time_end": _iso(np.datetime_as_string(times.max(), unit="s")),
                "time_count": int(times.size), "latitude": [float(latv.min()), float(latv.max())], "longitude": [float(lonv.min()), float(lonv.max())],
                "latitude_ascending": bool(latv[-1] > latv[0]), "longitude_convention": "0_360" if lonv.max() > 180 else "-180_180",
                "resolution": {"latitude": float(np.median(np.abs(np.diff(latv)))) if latv.size > 1 else None, "longitude": float(np.median(np.abs(np.diff(lonv)))) if lonv.size > 1 else None},
                "valid_ratio": float(finite.mean()), "speed_min": float(speed.min()) if speed.size else None, "speed_max": float(speed.max()) if speed.size else None,
            }
    except Exception as exc:
        raise ValueError(f"NetCDF 质量检查失败：{exc}") from exc


def register_file(source: Path, original_filename: str, request: dict | None = None) -> dict:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = settings.era5_raw_dir / f"{digest[:16]}.nc"
    settings.era5_raw_dir.mkdir(parents=True, exist_ok=True)
    quality = inspect_netcdf(source)
    if source.resolve() != destination.resolve(): shutil.copy2(source, destination)
    request = request or {"source": "manual_import"}
    with SessionLocal() as db:
        existing = db.scalar(select(Era5File).where(Era5File.sha256 == digest))
        if existing: return serialize_file(existing)
        item = Era5File(request_hash=request.get("request_fingerprint") or (_request_hash(request) if request.get("source") != "manual_import" else digest), original_filename=original_filename,
            local_path=str(destination), sha256=digest, file_size=destination.stat().st_size, request=request,
            coverage={key: quality[key] for key in ("time_start", "time_end", "time_count", "latitude", "longitude", "resolution")}, quality_report=quality)
        db.add(item); db.commit(); db.refresh(item); return serialize_file(item)


def serialize_file(item: Era5File) -> dict:
    return {"id": item.id, "request_hash": item.request_hash, "original_filename": item.original_filename, "file_size": item.file_size,
        "dataset": item.dataset, "request": item.request, "coverage": item.coverage, "quality_report": item.quality_report,
        "status": item.status, "acquired_at": _iso(item.acquired_at)}


def list_files() -> list[dict]:
    with SessionLocal() as db: return [serialize_file(x) for x in db.scalars(select(Era5File).order_by(Era5File.id.desc()))]


def download_public_sample() -> dict:
    """从公共 ARCO 镜像下载一个完整四时次真实 ERA5 样本。"""
    samples = build_samples("strict")
    if not samples:
        raise ValueError("没有可用于 ERA5 对齐的严格强度样本")
    sample = samples[0]
    moments = [sample.forecast_time - timedelta(hours=hours) for hours in OFFSETS]
    with SessionLocal() as db:
        rows = list(db.scalars(select(TyphoonObservation).where(
            TyphoonObservation.typhoon_id == sample.typhoon_id,
            TyphoonObservation.observation_time.in_(moments),
            TyphoonObservation.track_type == "MAIN",
        )))
    by_time = {row.observation_time: row for row in rows}
    if any(moment not in by_time for moment in moments):
        raise ValueError("严格样本缺少轨迹中心")
    centers = [(by_time[m].cma_lat or by_time[m].latitude, by_time[m].cma_lon or by_time[m].longitude) for m in moments]
    if any(lon < 0 or lon > 360 for _, lon in centers):
        raise ValueError("公共样本暂不支持跨本初子午线或日界线范围")
    north = np.ceil((max(lat for lat, _ in centers) + 4) * 4) / 4
    south = np.floor((min(lat for lat, _ in centers) - 4) * 4) / 4
    west = np.floor((min(lon for _, lon in centers) - 4) * 4) / 4
    east = np.ceil((max(lon for _, lon in centers) + 4) * 4) / 4
    variables = ["10m_u_component_of_wind", "10m_v_component_of_wind"]
    dataset = xr.open_zarr(PUBLIC_ARCO_URL, chunks=None, consolidated=True)
    try:
        subset = dataset[variables].sel(
            time=np.asarray(moments, dtype="datetime64[ns]"),
            latitude=slice(north, south), longitude=slice(west, east),
        ).load()
    finally:
        dataset.close()
    subset = subset.rename({variables[0]: "u10", variables[1]: "v10"})
    subset["u10"].attrs.update(units="m s**-1", long_name="10 metre U wind component")
    subset["v10"].attrs.update(units="m s**-1", long_name="10 metre V wind component")
    settings.era5_raw_dir.mkdir(parents=True, exist_ok=True)
    temporary = settings.era5_raw_dir / f"arco-era5-{sample.sid}-{sample.forecast_time:%Y%m%d%H}.tmp.nc"
    request = {
        "source": "google_public_arco_era5", "upstream_producer": "ECMWF Copernicus Climate Change Service",
        "public_store": PUBLIC_ARCO_URL, "sid": sample.sid,
        "times": [_iso(moment) for moment in moments], "area": [float(north), float(west), float(south), float(east)],
        "variables": variables, "license": "Copernicus C3S/CAMS License",
    }
    try:
        subset.to_netcdf(temporary, engine="h5netcdf")
        registered = register_file(temporary, temporary.name.replace(".tmp", ""), request)
    finally:
        temporary.unlink(missing_ok=True)
        subset.close()
    built = build_spatiotemporal_samples(limit=1)
    return {"file": registered, "sample": {"sid": sample.sid, "forecast_time": _iso(sample.forecast_time)}, "build": built}


def _public_plan(per_split: int = 2) -> list[dict]:
    """按集合和独立事件优先选样，避免同一台风的高度重叠窗口占满批次。"""
    samples=build_samples("strict")
    existing_rows=_spatiotemporal_rows()
    existing={(row.sid,row.forecast_time) for row in existing_rows}
    existing_sids={row.sid for row in existing_rows}
    selected=[]
    for split in ("train","validation","test"):
        seen=set(existing_sids)
        candidates=[x for x in samples if x.split==split and (x.sid,x.forecast_time) not in existing]
        # Freeze selection before any download: new events first, then stable
        # chronological order.  This avoids choosing samples by model error.
        candidates.sort(key=lambda x:(x.sid in existing_sids,x.forecast_time,x.sid))
        for sample in candidates:
            if sample.sid in seen:continue
            moments=[sample.forecast_time-timedelta(hours=h) for h in OFFSETS]
            selected.append({"sid":sample.sid,"typhoon_id":sample.typhoon_id,"split":split,"forecast_time":_iso(sample.forecast_time),"target_time":_iso(sample.target_time),"moments":[_iso(x) for x in moments],"estimated_bytes":100_000,"estimated_remote_bytes":len(moments)*2*ARCO_CHUNK_ESTIMATE_BYTES,"selection_rule":"new_event_then_chronological"})
            seen.add(sample.sid)
            if sum(1 for x in selected if x["split"]==split)>=per_split:break
    return selected


def _spatiotemporal_rows():
    with SessionLocal() as db:return list(db.scalars(select(SpatiotemporalSample)))


def public_batch_preview(per_split:int=2)->dict:
    plan=_public_plan(per_split);source_id=choose_source({});estimated=sum(x["estimated_bytes"] for x in plan);remote=0
    for item in plan:
        sample=_sample_by_key(item["sid"],item["forecast_time"])
        if sample:
            estimate=ADAPTERS[source_id].estimate(_sample_remote_request(sample));item["source_id"]=source_id;item["source_estimate"]=estimate;item["estimated_remote_bytes"]=int(estimate.get("estimated_uncompressed_bytes") or 0);remote+=item["estimated_remote_bytes"]
    free=shutil.disk_usage(settings.era5_raw_dir.parent if settings.era5_raw_dir.parent.exists() else settings.era5_raw_dir.parents[1]).free
    return {"plan":plan,"samples":len(plan),"source_id":source_id,"estimated_bytes":estimated,"estimated_remote_bytes":remote,"disk_free_bytes":free,"disk_budget_bytes":int(settings.era5_disk_budget_gb*1024**3),"remote_budget_bytes":int(settings.era5_remote_batch_budget_gb*1024**3),"max_concurrency":settings.era5_max_workers,"access":ADAPTERS[source_id].name,"warning":"远程量是按分块元数据计算的未压缩估算，不是实测流量。"}


def _sample_by_key(sid:str,forecast_time:str):
    wanted=datetime.fromisoformat(forecast_time.replace("Z","+00:00")).replace(tzinfo=None)
    return next((x for x in build_samples("strict") if x.sid==sid and x.forecast_time==wanted),None)


def _archive_public_sample(sample, dataset:xr.Dataset)->dict:
    moments=[sample.forecast_time-timedelta(hours=h) for h in OFFSETS]
    with SessionLocal() as db:
        rows=list(db.scalars(select(TyphoonObservation).where(TyphoonObservation.typhoon_id==sample.typhoon_id,TyphoonObservation.observation_time.in_(moments),TyphoonObservation.track_type=="MAIN")))
    by_time={x.observation_time:x for x in rows}
    if any(moment not in by_time for moment in moments):raise ValueError("严格样本缺少四个历史轨迹中心")
    centers=[(by_time[m].cma_lat or by_time[m].latitude,by_time[m].cma_lon or by_time[m].longitude) for m in moments]
    if any(lon<0 or lon>360 for _,lon in centers):raise ValueError("当前公共批次暂不处理跨日界线归档")
    north=np.ceil((max(x[0] for x in centers)+4)*4)/4;south=np.floor((min(x[0] for x in centers)-4)*4)/4
    west=np.floor((min(x[1] for x in centers)-4)*4)/4;east=np.ceil((max(x[1] for x in centers)+4)*4)/4
    variables=["10m_u_component_of_wind","10m_v_component_of_wind"]
    subset=dataset[variables].sel(time=np.asarray(moments,dtype="datetime64[ns]"),latitude=slice(north,south),longitude=slice(west,east)).load().rename({variables[0]:"u10",variables[1]:"v10"})
    subset["u10"].attrs["units"]="m s**-1";subset["v10"].attrs["units"]="m s**-1"
    temporary=settings.era5_raw_dir/f"arco-era5-{sample.sid}-{sample.forecast_time:%Y%m%d%H}.tmp.nc"
    request={"source":"google_public_arco_era5","upstream_producer":"ECMWF Copernicus Climate Change Service","public_store":PUBLIC_ARCO_URL,"sid":sample.sid,"times":[_iso(x) for x in moments],"area":[float(north),float(west),float(south),float(east)],"variables":variables,"processing_version":PROCESSING_VERSION}
    try:
        subset.to_netcdf(temporary,engine="h5netcdf");return register_file(temporary,temporary.name.replace(".tmp",""),request)
    finally:temporary.unlink(missing_ok=True);subset.close()


def _sample_remote_request(sample)->dict:
    moments=[sample.forecast_time-timedelta(hours=h) for h in OFFSETS]
    with SessionLocal() as db:
        rows=list(db.scalars(select(TyphoonObservation).where(TyphoonObservation.typhoon_id==sample.typhoon_id,TyphoonObservation.observation_time.in_(moments),TyphoonObservation.track_type=="MAIN")))
    by_time={x.observation_time:x for x in rows}
    if any(moment not in by_time for moment in moments):raise ValueError("严格样本缺少四个历史轨迹中心")
    centers=[(by_time[m].cma_lat or by_time[m].latitude,by_time[m].cma_lon or by_time[m].longitude) for m in moments]
    if any(lon<0 or lon>360 for _,lon in centers):raise ValueError("当前公共批次暂不处理跨日界线归档")
    north=np.ceil((max(x[0] for x in centers)+4)*4)/4;south=np.floor((min(x[0] for x in centers)-4)*4)/4
    west=np.floor((min(x[1] for x in centers)-4)*4)/4;east=np.ceil((max(x[1] for x in centers)+4)*4)/4
    return {"sid":sample.sid,"times":[_iso(x) for x in moments],"centers":[list(x) for x in centers],"area":[float(north),float(west),float(south),float(east)],"network_timeout_seconds":settings.era5_network_timeout_seconds}


def _adapter_cache_key(request:dict)->dict:
    value={key:request.get(key) for key in ("source_id","dataset_version","sid","times","centers","area","variables","processing_version","crop_version")}
    if value["source_id"] in {"google_arco","aws_icechunk"} and value["crop_version"] is None:value["crop_version"]=CROP_VERSION
    return value


def _find_adapter_cache(cache_key:dict):
    with SessionLocal() as db:
        for row in db.scalars(select(Era5File).where(Era5File.status=="valid")):
            if _adapter_cache_key(row.request or {})==cache_key:return serialize_file(row)
    return None


def _archive_via_adapter(sample,source_id:str,signal:threading.Event)->tuple[dict,dict]:
    request=_sample_remote_request(sample);state=load_source_state()
    if source_id=="aws_icechunk":request["snapshot_id"]=((state.get("sources") or {}).get(source_id) or {}).get("snapshot_id")
    dataset_version=request.get("snapshot_id") if source_id=="aws_icechunk" else "google-arco-analysis-ready"
    archive_request={"source":"aws_earthmover_icechunk_era5" if source_id=="aws_icechunk" else "google_public_arco_era5","source_id":source_id,"upstream_producer":"ECMWF Copernicus Climate Change Service","dataset_version":dataset_version,"snapshot_id":dataset_version if source_id=="aws_icechunk" else None,"bucket":"earthmover-icechunk-era5" if source_id=="aws_icechunk" else None,"prefix":"icechunkV2" if source_id=="aws_icechunk" else None,"group":"single/temporal" if source_id=="aws_icechunk" else None,"sid":sample.sid,"times":request["times"],"centers":request["centers"],"area":request["area"],"variables":["u10","v10"],"processing_version":PROCESSING_VERSION,"crop_version":CROP_VERSION,"actual_transfer_bytes":None,"http_requests":None}
    cache_key=_adapter_cache_key(archive_request);cached=_find_adapter_cache(cache_key)
    if cached:return cached,{"source_id":source_id,"dataset_version":dataset_version,"read_seconds":0.0,"actual_transfer_bytes":0,"http_requests":0,"local_bytes":cached["file_size"],"cache_hit":True,"completed_at":_iso(datetime.now(UTC))}
    temporary=settings.era5_raw_dir/f"{source_id}-{sample.sid}-{sample.forecast_time:%Y%m%d%H}.worker.nc"
    try:
        metrics=run_read_worker(source_id,request,temporary,settings.era5_sample_timeout_seconds,signal.is_set)
        archive_request["dataset_version"]=metrics["dataset_version"];archive_request["snapshot_id"]=metrics["dataset_version"] if source_id=="aws_icechunk" else None;archive_request["accessed_at"]=metrics["completed_at"];archive_request["request_fingerprint"]=_request_hash(_adapter_cache_key(archive_request));metrics["cache_hit"]=False
        return register_file(temporary,temporary.name.replace(".worker",""),archive_request),metrics
    finally:
        temporary.unlink(missing_ok=True);temporary.with_suffix(".partial.nc").unlink(missing_ok=True)


def create_public_batch(per_split:int=2)->dict:
    if per_split<1 or per_split>min(10,settings.era5_batch_max_samples):raise ValueError("每个集合批量数超出受控范围")
    preview=public_batch_preview(per_split)
    if not preview["plan"]:raise ValueError("没有新的可选严格样本")
    used=sum(p.stat().st_size for p in settings.era5_raw_dir.glob("*") if p.is_file()) if settings.era5_raw_dir.exists() else 0
    if used+preview["estimated_bytes"]>preview["disk_budget_bytes"] or preview["disk_free_bytes"]<preview["estimated_bytes"]*2:raise ValueError("磁盘预算不足，未创建批次")
    if preview["estimated_remote_bytes"]>preview["remote_budget_bytes"]:raise ValueError("保守估算的远程读取量超过单批预算，请减小批次")
    batch_id=str(uuid4())
    with SessionLocal() as db:
        db.add(Era5SampleBatch(id=batch_id,status="queued",requested=len(preview["plan"]),estimated_bytes=preview["estimated_bytes"],estimated_remote_bytes=preview["estimated_remote_bytes"],processing_version=PROCESSING_VERSION,source_id=preview["source_id"],plan=preview["plan"]));db.commit()
    signal=threading.Event();_batch_signals[batch_id]=signal;_executor.submit(_run_public_batch,batch_id,signal)
    return get_public_batch(batch_id)


def _run_public_batch(batch_id:str,signal:threading.Event):
    errors=[];dataset=None;started=time.perf_counter();performance=[]
    try:
        with SessionLocal() as db:
            row=db.get(Era5SampleBatch,batch_id);row.status="running";row.cancel_requested=False;row.started_at=row.started_at or datetime.now(UTC);plan=list(row.plan);source_id=row.source_id or choose_source({});cursor=row.cursor or 0;completed=row.completed or 0;actual=row.actual_bytes or 0;cache_hits=row.cache_hits or 0;errors=list(row.errors or []);performance=list((row.metrics or {}).get("items",[]));db.commit()
        candidates={(x.sid,x.forecast_time):x for x in build_samples("strict")}
        for index,item in enumerate(plan[cursor:],start=cursor):
            if signal.is_set():raise InterruptedError("用户暂停批次")
            if time.perf_counter()-started>settings.era5_batch_timeout_seconds:raise TimeoutError("批次达到超时预算，已安全停止")
            try:
                wanted=datetime.fromisoformat(item["forecast_time"].replace("Z","+00:00")).replace(tzinfo=None)
                sample=candidates.get((item["sid"],wanted))
                if not sample:raise ValueError("严格样本清单中不存在")
                result,metrics=_archive_via_adapter(sample,source_id,signal);completed+=1;actual+=int(result["file_size"]);cache_hits+=int(bool(metrics.get("cache_hit")));performance.append({"sid":item["sid"],"forecast_time":item["forecast_time"],**metrics})
            except InterruptedError:raise
            except Exception as exc:errors.append({"sid":item["sid"],"forecast_time":item["forecast_time"],"error":f"{type(exc).__name__}: {exc}"})
            with SessionLocal() as db:
                row=db.get(Era5SampleBatch,batch_id);row.completed=completed;row.failed=len(errors);row.actual_bytes=actual;row.cache_hits=cache_hits;row.remote_requests=0;row.cursor=index+1;row.duration_seconds=time.perf_counter()-started;row.errors=errors;row.metrics={"items":performance,"actual_transfer_bytes":None,"http_requests":None};db.commit()
        keys={(x["sid"],datetime.fromisoformat(x["forecast_time"].replace("Z","+00:00")).replace(tzinfo=None)) for x in plan}
        built=build_spatiotemporal_samples(sample_keys=keys)
        with SessionLocal() as db:
            row=db.get(Era5SampleBatch,batch_id);row.status="succeeded" if not errors else "partial";row.finished_at=datetime.now(UTC);row.duration_seconds=time.perf_counter()-started;row.errors=errors;row.metrics={**(row.metrics or {}),"build":built};db.commit()
    except InterruptedError as exc:
        with SessionLocal() as db:
            row=db.get(Era5SampleBatch,batch_id);row.status="paused";row.duration_seconds=time.perf_counter()-started;row.errors=errors;row.failed=len(errors);row.metrics={**(row.metrics or {}),"last_pause":{"message":str(exc),"at":_iso(datetime.now(UTC))}};db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            row=db.get(Era5SampleBatch,batch_id);row.status="failed";row.finished_at=datetime.now(UTC);row.duration_seconds=time.perf_counter()-started;row.errors=errors+[{"error":f"{type(exc).__name__}: {exc}"}];db.commit()
    finally:
        if dataset is not None:dataset.close()
        _batch_signals.pop(batch_id,None)


def _batch_dict(row):
    return {c.name:(_iso(getattr(row,c.name)) if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in Era5SampleBatch.__table__.columns}


def get_public_batch(batch_id:str)->dict:
    with SessionLocal() as db:
        row=db.get(Era5SampleBatch,batch_id)
        if not row:raise LookupError("批次不存在")
        return _batch_dict(row)


def list_public_batches()->list[dict]:
    with SessionLocal() as db:return [_batch_dict(x) for x in db.scalars(select(Era5SampleBatch).order_by(Era5SampleBatch.created_at.desc()))]


def cancel_public_batch(batch_id:str)->dict:
    with SessionLocal() as db:
        row=db.get(Era5SampleBatch,batch_id)
        if not row:raise LookupError("批次不存在")
        row.cancel_requested=True;db.commit()
    signal=_batch_signals.get(batch_id)
    if signal:signal.set()
    return get_public_batch(batch_id)


def benchmark_source(source_id:str)->dict:
    if source_id not in ADAPTERS:raise ValueError("不支持的数据源")
    if source_id=="ecmwf_arco":raise ValueError("ECMWF ARCO 未授权，不能执行真实读取")
    with SessionLocal() as db:
        row=db.scalar(select(SpatiotemporalSample).where(SpatiotemporalSample.processing_version==PROCESSING_VERSION).order_by(SpatiotemporalSample.forecast_time))
    if not row:raise ValueError("没有可用于固定基准的 v2 样本")
    sample=next((x for x in build_samples("strict") if x.sid==row.sid and x.forecast_time==row.forecast_time),None)
    if not sample:raise ValueError("固定基准不在严格候选清单")
    request=_sample_remote_request(sample);state=load_source_state()
    if source_id=="aws_icechunk":request["snapshot_id"]=((state.get("sources") or {}).get(source_id) or {}).get("snapshot_id")
    estimate=ADAPTERS[source_id].estimate(request);budget=int(settings.era5_remote_batch_budget_gb*1024**3)
    if (estimate.get("estimated_uncompressed_bytes") or 0)>budget:
        result={"source_id":source_id,"status":"budget_limited","sample_id":row.id,"sid":row.sid,"estimate":estimate,"actual_transfer_bytes":None,"http_requests":None,"checked_at":_iso(datetime.now(UTC))}
    else:
        temporary=settings.era5_raw_dir/f"benchmark-{source_id}-{row.sid}.nc";signal=threading.Event()
        try:
            cold=run_read_worker(source_id,request,temporary,settings.era5_sample_timeout_seconds,signal.is_set)
            centers=request["centers"];moments=[datetime.fromisoformat(x.replace("Z","+00:00")).replace(tzinfo=None) for x in request["times"]]
            remote=np.stack([extract_grid(temporary,m,*center)[0] for m,center in zip(moments,centers)])
            with np.load(row.local_path,allow_pickle=False) as item:reference=np.asarray(item["wind"],np.float32)
            difference=np.abs(reference-remote);tolerance=.002
            result={"source_id":source_id,"status":"succeeded" if float(difference.max())<=tolerance else "quality_failed","sample_id":row.id,"sid":row.sid,"forecast_time":_iso(row.forecast_time),"cold_read_seconds":cold["read_seconds"],"warm_read_seconds":None,"cache_mode":"isolated_cold_process","actual_transfer_bytes":None,"http_requests":None,"estimated":estimate,"shape":list(remote.shape),"finite":bool(np.isfinite(remote).all()),"max_abs_difference":float(difference.max()),"mean_abs_difference":float(difference.mean()),"tolerance_m_s":tolerance,"dataset_version":cold["dataset_version"],"local_archive_bytes":cold["local_bytes"],"checked_at":_iso(datetime.now(UTC))}
        finally:temporary.unlink(missing_ok=True);temporary.with_suffix(".partial.nc").unlink(missing_ok=True)
    state=load_source_state();state.setdefault("benchmarks",{})[source_id]=result;save_source_state(state);return result


def resume_public_batch(batch_id:str)->dict:
    with SessionLocal() as db:
        row=db.get(Era5SampleBatch,batch_id)
        if not row:raise LookupError("批次不存在")
        if row.status not in {"paused","failed","partial"}:raise ValueError("仅暂停、失败或部分完成的批次可恢复")
        if row.cursor>=row.requested:raise ValueError("批次已经处理完毕")
        row.errors=_data_batch_errors(row.errors);row.failed=len(row.errors);row.status="queued";row.cancel_requested=False;row.finished_at=None;db.commit()
    signal=threading.Event();_batch_signals[batch_id]=signal;_executor.submit(_run_public_batch,batch_id,signal)
    return get_public_batch(batch_id)


def _normalized(ds: xr.Dataset, lat: str, lon: str) -> xr.Dataset:
    ds = ds.sortby(lat)
    values = ((np.asarray(ds[lon].values, float) + 180) % 360) - 180
    ds = ds.assign_coords({lon: values}).sortby(lon)
    left, right = ds.assign_coords({lon: ds[lon] - 360}), ds.assign_coords({lon: ds[lon] + 360})
    return xr.concat([left, ds, right], dim=lon).sortby(lon)


def extract_grid(path: Path, moment: datetime, center_lat: float, center_lon: float) -> tuple[np.ndarray, dict]:
    ds = _open_loaded(path)
    u, v, lat, lon, time = _names(ds)
    if not all((u, v, lat, lon, time)): raise ValueError("文件字段不完整")
    ds = _normalized(ds, lat, lon)
    target_lat = center_lat + np.arange(-15, 16) * 0.25
    target_lon = center_lon + np.arange(-15, 16) * 0.25
    chosen = ds.sel({time: np.datetime64(moment)}, method="nearest", tolerance=np.timedelta64(1, "h"))
    field = chosen[[u, v]].interp({lat: target_lat, lon: target_lon}, method="linear")
    array = np.stack([np.asarray(field[u].values, np.float32), np.asarray(field[v].values, np.float32)])
    finite = np.isfinite(array); speed = np.sqrt(array[0] ** 2 + array[1] ** 2)
    stats = {"valid_ratio": float(finite.mean()), "speed_min": float(np.nanmin(speed)), "speed_max": float(np.nanmax(speed)),
        "speed_mean": float(np.nanmean(speed)), "shape": list(array.shape), "grid_spacing_degree": 0.25,
        "latitude_order": "south_to_north", "center": [center_lat, center_lon], "time": _iso(moment)}
    if array.shape != (2, 31, 31) or stats["valid_ratio"] < 0.999 or stats["speed_max"] > 150:
        raise ValueError(f"裁剪风场质量不合格：{stats}")
    return array, stats


def _find_covering_file(files: list[Era5File], moment: datetime, lat: float, lon: float) -> Era5File | None:
    lon180 = ((lon + 180) % 360) - 180
    for item in files:
        c = item.coverage or {}; q = item.quality_report or {}
        try:
            t0, t1 = np.datetime64(c["time_start"]), np.datetime64(c["time_end"])
            lo0, lo1 = map(float, c["longitude"]); la0, la1 = map(float, c["latitude"])
            candidates = [lon180, lon180 % 360]
            if t0 <= np.datetime64(moment) <= t1 and la0 <= lat <= la1 and any(lo0 <= x <= lo1 for x in candidates) and q.get("valid"):
                return item
        except (KeyError, TypeError, ValueError): continue
    return None


def build_spatiotemporal_samples(limit: int | None = None, sample_keys: set[tuple[str, datetime]] | None = None) -> dict:
    samples = build_samples("strict")
    if sample_keys is not None: samples=[x for x in samples if (x.sid,x.forecast_time) in sample_keys]
    built = skipped = reused = 0
    reasons: dict[str, int] = {}
    settings.era5_processed_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        files = list(db.scalars(select(Era5File).where(Era5File.status == "valid")))
        if sample_keys is None:
            archived={(str((item.request or {}).get("sid")),str(moment)) for item in files for moment in ((item.request or {}).get("times") or []) if (item.request or {}).get("sid")}
            samples=[x for x in samples if (x.sid,_iso(x.forecast_time)) in archived]
        if limit: samples = samples[:limit]
        for sample in samples:
            existing = db.scalar(select(SpatiotemporalSample).where(SpatiotemporalSample.sid == sample.sid, SpatiotemporalSample.forecast_time == sample.forecast_time, SpatiotemporalSample.processing_version == PROCESSING_VERSION))
            if existing: reused += 1; continue
            moments = [sample.forecast_time - timedelta(hours=h) for h in OFFSETS]
            observations = list(db.scalars(select(TyphoonObservation).where(TyphoonObservation.typhoon_id == sample.typhoon_id, TyphoonObservation.observation_time.in_(moments), TyphoonObservation.track_type == "MAIN").order_by(TyphoonObservation.id.desc())))
            by_time = {}
            for row in observations: by_time.setdefault(row.observation_time, row)
            arrays=[]; field_ids=[]
            try:
                for moment in moments:
                    row=by_time.get(moment)
                    if not row: raise ValueError("missing_track_center")
                    lat, lon = row.cma_lat or row.latitude, row.cma_lon or row.longitude
                    source = _find_covering_file(files, moment, lat, lon)
                    if not source: raise ValueError("missing_era5_coverage")
                    field = db.scalar(select(WindFieldSample).where(WindFieldSample.sid == sample.sid, WindFieldSample.observation_time == moment, WindFieldSample.processing_version == CROP_VERSION))
                    if field:
                        array=np.load(field.local_path)["wind"]
                    else:
                        array, stats=extract_grid(Path(source.local_path), moment, lat, lon)
                        field_dir=settings.era5_processed_dir / "wind_fields"; field_dir.mkdir(parents=True, exist_ok=True)
                        field_path=field_dir / f"{sample.sid}_{moment:%Y%m%d%H}_{CROP_VERSION}.npz"; np.savez_compressed(field_path, wind=array)
                        field=WindFieldSample(era5_file_id=source.id,typhoon_id=sample.typhoon_id,sid=sample.sid,observation_time=moment,center_latitude=lat,center_longitude=lon,local_path=str(field_path),statistics=stats,processing_version=CROP_VERSION)
                        db.add(field); db.flush()
                    arrays.append(array); field_ids.append(field.id)
                cube=np.stack(arrays).astype(np.float32)
                if cube.shape != (4,2,31,31): raise ValueError("invalid_cube_shape")
                sample_id=hashlib.sha256(f"{sample.sid}|{sample.forecast_time.isoformat()}|{PROCESSING_VERSION}".encode()).hexdigest()[:32]
                out_dir=settings.era5_processed_dir / "spatiotemporal"; out_dir.mkdir(parents=True,exist_ok=True)
                out=out_dir / f"{sample_id}.npz"
                np.savez_compressed(out,wind=cube,temporal=np.asarray(sample.ridge_features,np.float32),target=np.float32(sample.target))
                digest=hashlib.sha256(out.read_bytes()).hexdigest()
                db.add(SpatiotemporalSample(id=sample_id,typhoon_id=sample.typhoon_id,sid=sample.sid,forecast_time=sample.forecast_time,target_time=sample.target_time,split=sample.split,target_wind=sample.target,temporal_features=sample.ridge_features,wind_field_ids=field_ids,local_path=str(out),processing_version=PROCESSING_VERSION,quality_report={"shape":list(cube.shape),"finite":bool(np.isfinite(cube).all()),"sha256":digest,"input_times":[_iso(x) for x in moments],"source_file_ids":sorted({x.era5_file_id for x in db.scalars(select(WindFieldSample).where(WindFieldSample.id.in_(field_ids)))})}))
                db.commit(); built += 1
            except ValueError as exc:
                db.rollback(); skipped += 1; reasons[str(exc)] = reasons.get(str(exc),0)+1
    return {"built":built,"reused":reused,"skipped":skipped,"skip_reasons":reasons,"eligible_intensity_samples":len(samples)}


def sample_statistics() -> dict:
    with SessionLocal() as db:
        total=db.scalar(select(func.count()).select_from(SpatiotemporalSample).where(SpatiotemporalSample.processing_version==PROCESSING_VERSION)) or 0
        splits=dict(db.execute(select(SpatiotemporalSample.split,func.count()).where(SpatiotemporalSample.processing_version==PROCESSING_VERSION).group_by(SpatiotemporalSample.split)).all())
        fields=db.scalar(select(func.count()).select_from(WindFieldSample).where(WindFieldSample.processing_version==CROP_VERSION)) or 0
        files=db.scalar(select(func.count()).select_from(Era5File)) or 0
        versions=dict(db.execute(select(SpatiotemporalSample.processing_version,func.count()).group_by(SpatiotemporalSample.processing_version)).all())
        first=db.scalar(select(SpatiotemporalSample).where(SpatiotemporalSample.processing_version==PROCESSING_VERSION).order_by(SpatiotemporalSample.created_at.desc()))
        preview=None
        if first:
            cube=np.load(first.local_path)["wind"]; speed=np.sqrt(cube[:,0]**2+cube[:,1]**2)
            preview={"id":first.id,"sid":first.sid,"forecast_time":_iso(first.forecast_time),"target_time":_iso(first.target_time),"split":first.split,"target_wind":first.target_wind,
                "temporal_features":first.temporal_features,"shape":list(cube.shape),"u":cube[:,0].tolist(),"v":cube[:,1].tolist(),"speed_range":[float(speed.min()),float(speed.max())]}
    return {"era5_files":files,"wind_fields":fields,"spatiotemporal_samples":total,"splits":splits,"processing_version":PROCESSING_VERSION,"historical_versions":versions,"shape":[4,2,31,31],"dataset_version":dataset_version("strict"),"strict_reference":split_statistics(build_samples("strict")),"preview":preview}


def create_download_job(payload: dict) -> dict:
    if not credential_status()["configured"]: raise ValueError("未配置 CDS API 凭据，不能创建在线下载任务")
    request = payload["request"]; _validate_small_request(request); fingerprint = _request_hash(request)
    with SessionLocal() as db:
        cached=db.scalar(select(Era5File).where(Era5File.request_hash==fingerprint,Era5File.status=="valid"))
        job=Era5DownloadJob(id=str(uuid4()),request_hash=fingerprint,typhoon_id=payload.get("typhoon_id"),sid=payload.get("sid"),request=request,
            status="completed" if cached else "queued",phase="cache_hit" if cached else "queued",progress=100 if cached else None,file_id=cached.id if cached else None,finished_at=datetime.now(UTC) if cached else None)
        db.add(job);db.commit();result=serialize_job(job)
    if not cached:
        signal=threading.Event();_signals[job.id]=signal;_executor.submit(_run_download,job.id,signal)
    return result


def _validate_small_request(request: dict) -> None:
    variables=set(request.get("variable") or [])
    if variables!={"10m_u_component_of_wind","10m_v_component_of_wind"}:raise ValueError("仅允许同时下载 U10/V10")
    area=request.get("area")
    if not isinstance(area,list) or len(area)!=4:raise ValueError("area 必须为 [北,西,南,东]")
    north,west,south,east=map(float,area)
    if north<=south or east<=west or north-south>10 or east-west>10:raise ValueError("单个请求范围不得超过 10°×10°，跨日界线须拆分")
    for key in ("year","month","day","time"):
        value=request.get(key)
        if not isinstance(value,list) or len(value)!=1:raise ValueError("每个小范围任务只能包含一个时次")
    if request.get("data_format") not in {"netcdf","netcdf4"}:raise ValueError("数据格式必须为 NetCDF")


def _job_update(job_id:str,**fields):
    with SessionLocal() as db:
        row=db.get(Era5DownloadJob,job_id)
        if row:
            for key,value in fields.items():setattr(row,key,value)
            db.commit()


def _run_download(job_id:str,signal:threading.Event):
    target=settings.era5_raw_dir/f"download-{job_id}.nc"
    try:
        with SessionLocal() as db: job=db.get(Era5DownloadJob,job_id);request=dict(job.request)
        if signal.is_set():raise InterruptedError("任务在提交前已取消")
        used=sum(p.stat().st_size for p in settings.era5_raw_dir.glob("*") if p.is_file()) if settings.era5_raw_dir.exists() else 0
        if used>=settings.era5_disk_budget_gb*1024**3:raise ValueError("ERA5 缓存已达到磁盘预算")
        settings.era5_raw_dir.mkdir(parents=True,exist_ok=True)
        _job_update(job_id,status="submitting",phase="submitting_to_cds",started_at=datetime.now(UTC),progress=None)
        import cdsapi
        _job_update(job_id,status="processing",phase="cds_queue_or_processing",progress=None)
        cdsapi.Client(quiet=True).retrieve(DATASET,request,str(target))
        if used+target.stat().st_size>settings.era5_disk_budget_gb*1024**3:raise ValueError("下载完成但会超过 ERA5 磁盘预算，已丢弃临时文件")
        if signal.is_set():raise InterruptedError("CDS 请求已返回，但本地任务已取消")
        _job_update(job_id,status="validating",phase="validating_netcdf",progress=None,downloaded_bytes=target.stat().st_size)
        item=register_file(target,target.name,request)
        _job_update(job_id,status="completed",phase="completed",progress=100,file_id=item["id"],finished_at=datetime.now(UTC))
    except InterruptedError as exc:
        _job_update(job_id,status="cancelled",phase="cancelled",error_message=str(exc),finished_at=datetime.now(UTC))
    except Exception as exc:
        _job_update(job_id,status="failed",phase="failed",error_message=f"{type(exc).__name__}: {exc}",finished_at=datetime.now(UTC))
    finally:
        target.unlink(missing_ok=True);_signals.pop(job_id,None)


def serialize_job(job:Era5DownloadJob)->dict:
    return {column.name:(_iso(getattr(job,column.name)) if isinstance(getattr(job,column.name),datetime) else getattr(job,column.name)) for column in Era5DownloadJob.__table__.columns}


def list_jobs()->list[dict]:
    with SessionLocal() as db:return [serialize_job(x) for x in db.scalars(select(Era5DownloadJob).order_by(Era5DownloadJob.created_at.desc()))]


def cancel_job(job_id:str)->dict:
    with SessionLocal() as db:
        job=db.get(Era5DownloadJob,job_id)
        if not job:raise LookupError("任务不存在")
        if job.status not in ACTIVE_JOB_STATUSES:return serialize_job(job)
        job.cancel_requested=True;db.commit();result=serialize_job(job)
    signal=_signals.get(job_id)
    if signal:signal.set()
    return result


def retry_job(job_id:str)->dict:
    with SessionLocal() as db:
        job=db.get(Era5DownloadJob,job_id)
        if not job:raise LookupError("任务不存在")
        if job.status not in {"failed","cancelled","interrupted"}:raise ValueError("仅失败、取消或中断任务可重试")
        payload={"request":job.request,"typhoon_id":job.typhoon_id,"sid":job.sid}
    return create_download_job(payload)


def recover_download_jobs():
    with SessionLocal() as db:
        rows=list(db.scalars(select(Era5DownloadJob).where(Era5DownloadJob.status.in_(ACTIVE_JOB_STATUSES))))
        for row in rows:
            row.status="interrupted";row.phase="interrupted";row.error_message="应用退出时任务未完成，可手动重试。";row.finished_at=datetime.now(UTC)
        db.commit()


def recover_public_batches():
    """A process cannot retain remote sockets across restart; keep the cursor."""
    with SessionLocal() as db:
        rows=list(db.scalars(select(Era5SampleBatch).where(Era5SampleBatch.status.in_({"queued","running"}))))
        for row in rows:
            row.status="paused"
            row.metrics={**(row.metrics or {}),"last_pause":{"message":"应用退出时批次中断，可从已保存游标恢复。","at":_iso(datetime.now(UTC))}}
        for row in db.scalars(select(Era5SampleBatch).where(Era5SampleBatch.status=="partial")):
            row.errors=_data_batch_errors(row.errors)
            row.failed=len(row.errors)
            if row.completed>=row.requested and not row.errors:row.status="succeeded"
        db.commit()


def _operational_batch_event(item:dict)->bool:
    message=str(item.get("error", "")) if isinstance(item,dict) else ""
    return "用户暂停" in message or "应用退出时批次中断" in message


def _data_batch_errors(items)->list[dict]:
    return [item for item in (items or []) if isinstance(item,dict) and item.get("error") and not _operational_batch_event(item)]
