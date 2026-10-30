"""Isolated cloud reader; the parent owns timeout, termination and DB writes."""
from __future__ import annotations
import json,os,sys,time
from datetime import UTC,datetime
from pathlib import Path
import numpy as np
import xarray as xr

def _aws(request):
    import icechunk
    storage=icechunk.s3_storage(bucket="earthmover-icechunk-era5",prefix="icechunkV2",region="us-east-1",anonymous=True,network_stream_timeout_seconds=int(request.get("network_timeout_seconds",30)))
    repo=icechunk.Repository.open(storage);session=repo.readonly_session(snapshot_id=request.get("snapshot_id")) if request.get("snapshot_id") else repo.readonly_session("main")
    return xr.open_zarr(session.store,group="single/temporal",consolidated=False,chunks=None),session.snapshot_id
def _google(request):
    url="https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
    return xr.open_zarr(url,chunks=None,consolidated=True),"google-arco-analysis-ready"
def main(path):
    payload=json.loads(Path(path).read_text("utf-8"));request=payload["request"];started=time.perf_counter();ds,version=_aws(request) if payload["source_id"]=="aws_icechunk" else _google(request)
    north,west,south,east=map(float,request["area"]);times=np.asarray(request["times"],dtype="datetime64[ns]")
    if payload["source_id"]=="aws_icechunk":subset=ds[["u10","v10"]].sel(valid_time=times,latitude=slice(north,south),longitude=slice(west,east)).rename({"valid_time":"time"}).load()
    else:
        names=["10m_u_component_of_wind","10m_v_component_of_wind"];subset=ds[names].sel(time=times,latitude=slice(north,south),longitude=slice(west,east)).rename({names[0]:"u10",names[1]:"v10"}).load()
    subset.u10.attrs["units"]="m s**-1";subset.v10.attrs["units"]="m s**-1";target=Path(payload["target"]);partial=target.with_suffix(".partial.nc")
    subset.to_netcdf(partial,engine="h5netcdf");os.replace(partial,target)
    result={"source_id":payload["source_id"],"dataset_version":version,"read_seconds":time.perf_counter()-started,"actual_transfer_bytes":None,"http_requests":None,"local_bytes":target.stat().st_size,"shape":list(subset.u10.shape),"finite":bool(np.isfinite(subset.u10.values).all() and np.isfinite(subset.v10.values).all()),"completed_at":datetime.now(UTC).isoformat().replace("+00:00","Z")}
    Path(payload["metrics"]).write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8");subset.close();ds.close()
if __name__=="__main__":main(sys.argv[1])
