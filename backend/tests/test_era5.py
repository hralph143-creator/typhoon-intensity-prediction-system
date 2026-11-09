from datetime import datetime

import numpy as np
import xarray as xr
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import era5_service


def make_file(path, longitude=None, latitude=None):
    longitude=np.asarray(longitude if longitude is not None else np.arange(100,111,.25))
    latitude=np.asarray(latitude if latitude is not None else np.arange(30,19.75,-.25))
    times=np.asarray(["2024-08-01T00:00:00"],dtype="datetime64[s]")
    lon2,lat2=np.meshgrid(longitude,latitude)
    u=np.broadcast_to((lon2/100)[None],(1,len(latitude),len(longitude))).copy()
    v=np.broadcast_to((lat2/10)[None],u.shape).copy()
    ds=xr.Dataset({"u10":(("valid_time","latitude","longitude"),u,{"units":"m s-1"}),"v10":(("valid_time","latitude","longitude"),v,{"units":"m s-1"})},coords={"valid_time":times,"latitude":latitude,"longitude":longitude})
    path.write_bytes(ds.to_netcdf(engine="h5netcdf"))


def test_inspect_and_extract_normalizes_latitude(tmp_path):
    path=tmp_path/"sample.nc";make_file(path)
    report=era5_service.inspect_netcdf(path)
    assert report["valid"] and report["latitude_ascending"] is False
    array,stats=era5_service.extract_grid(path,datetime(2024,8,1),25,105)
    assert array.shape==(2,31,31)
    assert stats["latitude_order"]=="south_to_north"
    assert np.isfinite(array).all()
    assert array[1,0,15] < array[1,-1,15]


def test_extract_handles_dateline(tmp_path):
    path=tmp_path/"dateline.nc";make_file(path,longitude=np.arange(170,190.25,.25),latitude=np.arange(20,9.75,-.25))
    array,_=era5_service.extract_grid(path,datetime(2024,8,1),15,179)
    assert array.shape==(2,31,31) and np.isfinite(array).all()


def test_status_does_not_expose_secret(monkeypatch,tmp_path):
    monkeypatch.setattr(era5_service.Path,"home",lambda:tmp_path)
    (tmp_path/".cdsapirc").write_text("url: https://example.invalid\nkey: very-secret\n",encoding="utf-8")
    result=era5_service.credential_status()
    assert result["configured"] is True
    assert "very-secret" not in str(result)


def test_era5_api_empty_state():
    with TestClient(app) as client:
        response=client.get("/api/era5/status")
        assert response.status_code==200 and "configured" in response.json()["data"]
        stats=client.get("/api/era5/samples/statistics").json()["data"]
        assert stats["shape"]==[4,2,31,31]
        samples=client.get("/api/era5/samples",params={"split":"test","limit":10})
        assert samples.status_code==200 and samples.json()["data"]==[]
        assert client.get("/api/era5/samples/not-found").status_code==404


def test_rejects_wrong_units(tmp_path):
    path=tmp_path/"bad.nc";make_file(path)
    ds=era5_service._open_loaded(path);ds["u10"].attrs["units"]="knots";path.write_bytes(ds.to_netcdf(engine="h5netcdf"))
    try:
        era5_service.inspect_netcdf(path)
        assert False,"expected invalid units"
    except ValueError as exc:
        assert "单位" in str(exc)
