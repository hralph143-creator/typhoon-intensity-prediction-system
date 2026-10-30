"""Small, auditable adapter layer for the three approved ERA5 sources."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.config import settings

GOOGLE_URL = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
AWS_BUCKET = "earthmover-icechunk-era5"
AWS_PREFIX = "icechunkV2"
AWS_GROUP = "single/temporal"
ECMWF_GEO_URL = "https://arco.datastores.ecmwf.int/cadl-arco-geo-002/arco/reanalysis_era5_single_levels/sfc/geoChunked.zarr"
SOURCE_IDS = ("auto", "aws_icechunk", "google_arco", "ecmwf_arco")
STATE_PATH = settings.era5_processed_dir.parent.parent / "cache" / "era5-source-state.json"


def _now() -> str:return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def load_source_state() -> dict:
    try:
        value=json.loads(STATE_PATH.read_text("utf-8"));return value if isinstance(value,dict) else {}
    except (OSError,json.JSONDecodeError):return {}
def save_source_state(value:dict)->None:
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True);temporary=STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8");os.replace(temporary,STATE_PATH)


class Era5SourceAdapter(ABC):
    source_id:str;name:str;requires_auth=False
    @abstractmethod
    def probe(self)->dict:...
    @abstractmethod
    def estimate(self,request:dict)->dict:...
    def descriptor(self)->dict:
        state=load_source_state();return {"id":self.source_id,"name":self.name,"requires_auth":self.requires_auth,"last_result":(state.get("sources") or {}).get(self.source_id),"selected":state.get("default","auto")==self.source_id}


class GoogleArcoAdapter(Era5SourceAdapter):
    source_id="google_arco";name="Google ARCO-ERA5"
    def probe(self)->dict:
        import xarray as xr
        started=time.perf_counter();ds=xr.open_zarr(GOOGLE_URL,chunks=None,consolidated=True)
        try:
            u=ds["10m_u_component_of_wind"]
            return {"status":"available","checked_at":_now(),"metadata_seconds":time.perf_counter()-started,"dataset_version":"Google ARCO analysis-ready","layout":"time=1, latitude=721, longitude=1440","time_range":[str(ds.time.values[0]),str(ds.time.values[-1])],"variables":{"u10":True,"v10":True},"chunks":{"u10":list(u.encoding.get("chunks") or [])},"actual_transfer_bytes":None,"http_requests":None}
        finally:ds.close()
    def estimate(self,request:dict)->dict:
        chunks=len(request["times"])*2
        return {"estimated_chunks":chunks,"estimated_uncompressed_bytes":chunks*721*1440*4,"actual_transfer_bytes":None,"basis":"Zarr metadata; compressed transfer is not measured"}


class AwsIcechunkAdapter(Era5SourceAdapter):
    source_id="aws_icechunk";name="AWS Earthmover Icechunk ERA5"
    def _session(self):
        import icechunk
        storage=icechunk.s3_storage(bucket=AWS_BUCKET,prefix=AWS_PREFIX,region="us-east-1",anonymous=True,network_stream_timeout_seconds=settings.era5_network_timeout_seconds)
        repo=icechunk.Repository.open(storage);return repo,repo.readonly_session("main")
    def probe(self)->dict:
        import xarray as xr
        started=time.perf_counter();repo,session=self._session();ds=xr.open_zarr(session.store,group=AWS_GROUP,consolidated=False,chunks=None)
        try:
            return {"status":"available","checked_at":_now(),"metadata_seconds":time.perf_counter()-started,"dataset_version":session.snapshot_id,"branch":"main","snapshot_id":session.snapshot_id,"layout":"temporal","time_range":[str(ds.valid_time.values[0]),str(ds.valid_time.values[-1])],"variables":{"u10":"u10" in ds,"v10":"v10" in ds},"coordinates":{"time":"valid_time","latitude":"descending","longitude":"0_360"},"units":{"u10":ds.u10.attrs.get("units"),"v10":ds.v10.attrs.get("units")},"chunks":{"u10":list(ds.u10.encoding.get("chunks") or []),"v10":list(ds.v10.encoding.get("chunks") or [])},"actual_transfer_bytes":None,"http_requests":None}
        finally:ds.close()
    def estimate(self,request:dict)->dict:
        north,west,south,east=map(float,request["area"]);lat_cells=max(1,math.ceil((north-south)/.25)+1);lon_cells=max(1,math.ceil((east-west)/.25)+1)
        lat_chunks=math.ceil(lat_cells/12)+1;lon_chunks=math.ceil(lon_cells/12)+1;years={str(x)[:4] for x in request["times"]};chunks=len(years)*lat_chunks*lon_chunks*2
        return {"estimated_chunks":chunks,"estimated_uncompressed_bytes":chunks*8736*12*12*4,"actual_transfer_bytes":None,"basis":"temporal chunk metadata (8736,12,12); compressed transfer is not measured"}


class EcmwfArcoAdapter(Era5SourceAdapter):
    source_id="ecmwf_arco";name="ECMWF ERA5 ARCO geoChunked";requires_auth=True
    def probe(self)->dict:
        from backend.app.services.era5_service import credential_status
        if not credential_status()["configured"]:return {"status":"unauthorized","checked_at":_now(),"dataset_version":None,"layout":"geoChunked","variables":{"u10":None,"v10":None},"error":"CDS API credential is not configured"}
        return {"status":"not_tested","checked_at":_now(),"dataset_version":None,"layout":"geoChunked","variables":{"u10":None,"v10":None},"error":"Credential exists but remote probe has not run"}
    def estimate(self,request:dict)->dict:return {"estimated_chunks":None,"estimated_uncompressed_bytes":None,"actual_transfer_bytes":None,"basis":"metadata unavailable without authorization"}


ADAPTERS={x.source_id:x for x in (AwsIcechunkAdapter(),GoogleArcoAdapter(),EcmwfArcoAdapter())}
def source_descriptors()->list[dict]:return [adapter.descriptor() for adapter in ADAPTERS.values()]
def probe_source(source_id:str)->dict:
    if source_id not in ADAPTERS:raise ValueError("不支持的数据源")
    try:result=ADAPTERS[source_id].probe()
    except Exception as exc:result={"status":"network_failed","checked_at":_now(),"error":f"{type(exc).__name__}: {exc}","actual_transfer_bytes":None,"http_requests":None}
    state=load_source_state();state.setdefault("sources",{})[source_id]=result;state.setdefault("default","auto");save_source_state(state);return {"source_id":source_id,**result}
def set_default_source(source_id:str)->dict:
    if source_id not in SOURCE_IDS:raise ValueError("不支持的数据源")
    state=load_source_state()
    if source_id not in {"auto","google_arco"} and (state.get("sources",{}).get(source_id) or {}).get("status")!="available":raise ValueError("该数据源尚未实际验证可用")
    state["default"]=source_id;save_source_state(state);return {"default":source_id}
def choose_source(request:dict)->str:
    state=load_source_state();preferred=state.get("default","auto")
    if preferred!="auto":return preferred
    benchmarks=state.get("benchmarks",{});successful=[(float(value.get("cold_read_seconds",float("inf"))),source_id) for source_id,value in benchmarks.items() if value.get("status")=="succeeded" and source_id in {"aws_icechunk","google_arco"}]
    if successful:return min(successful)[1]
    return "aws_icechunk" if (state.get("sources",{}).get("aws_icechunk") or {}).get("status")=="available" else "google_arco"


def _stop_process(process:subprocess.Popen)->None:
    """Terminate a reader promptly, escalating to kill only if it ignores termination."""
    if process.poll() is not None:return
    process.terminate()
    try:process.wait(5)
    except subprocess.TimeoutExpired:
        process.kill();process.wait(5)


def run_read_worker(source_id:str,request:dict,target:Path,timeout_seconds:int,cancel_check=None)->dict:
    """Cloud I/O runs in a process that can really be terminated."""
    if source_id not in {"aws_icechunk","google_arco"}:raise ValueError("该数据源不支持匿名读取")
    estimate=ADAPTERS[source_id].estimate(request);budget=int(settings.era5_remote_batch_budget_gb*1024**3)
    if (estimate.get("estimated_uncompressed_bytes") or 0)>budget:raise ValueError("budget_limited")
    target.parent.mkdir(parents=True,exist_ok=True);request_path=target.with_suffix(".request.json");metrics_path=target.with_suffix(".metrics.json")
    request_path.write_text(json.dumps({"source_id":source_id,"request":request,"target":str(target),"metrics":str(metrics_path)},ensure_ascii=False),encoding="utf-8")
    process=subprocess.Popen([sys.executable,"-m","backend.app.services.era5_worker",str(request_path)],cwd=str(settings.era5_raw_dir.parents[2]),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace");started=time.perf_counter()
    try:
        while process.poll() is None:
            if cancel_check and cancel_check():_stop_process(process);raise InterruptedError("用户暂停，读取子进程已终止")
            if time.perf_counter()-started>timeout_seconds:_stop_process(process);raise TimeoutError("单样本读取超过时间预算，子进程已终止")
            time.sleep(.25)
        stderr=process.stderr.read() if process.stderr else ""
        if process.returncode:raise RuntimeError(stderr[-1000:] or f"worker exited {process.returncode}")
        result=json.loads(metrics_path.read_text("utf-8"));result["estimate"]=estimate;return result
    finally:
        request_path.unlink(missing_ok=True);metrics_path.unlink(missing_ok=True)
        if process.poll() is None:_stop_process(process)
