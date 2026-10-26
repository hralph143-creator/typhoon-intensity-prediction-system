from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.models.era5 import SpatiotemporalSample
from backend.app.services.ml_dataset import audit_data, build_samples, dataset_version, split_statistics
from backend.app.services.ml_training import cancel_experiment, create_experiment, delete_experiment, get_experiment, historical_predict, list_experiments, list_models
from backend.app.services.safnet_training import predict as safnet_predict, structure_info

router = APIRouter(prefix="/ml", tags=["历史强度预测"])


def ok(data, message="请求成功"):
    return {"success": True, "message": message, "data": data}


class ExperimentCreate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    model_type: str
    quality_profile: str = "strict"
    config: dict = Field(default_factory=dict)


class BacktestRequest(BaseModel):
    model_id: str
    typhoon_id: int
    forecast_time: datetime


class SAFNetPredictRequest(BaseModel):
    model_id: str
    sample_id: str
    include_attention: bool = False


@router.get("/audit")
def audit(): return ok(audit_data())


@router.get("/samples/statistics")
def sample_statistics(quality_profile: str = Query("strict", pattern="^(strict|extended)$")):
    samples = build_samples(quality_profile)
    return ok({"quality_profile": quality_profile, "dataset_version": dataset_version(quality_profile), "total": len(samples), "splits": split_statistics(samples)})


@router.get("/experiments")
def experiments(model_type: str | None = None, status: str | None = None): return ok(list_experiments(model_type, status))


@router.post("/experiments", status_code=202)
def start(payload: ExperimentCreate):
    try: return ok(create_experiment(payload.model_dump()), "训练任务已创建")
    except ValueError as exc: raise HTTPException(409, str(exc))


@router.get("/experiments/{experiment_id}")
def experiment(experiment_id: str):
    try: return ok(get_experiment(experiment_id))
    except LookupError as exc: raise HTTPException(404, str(exc))


@router.post("/experiments/{experiment_id}/cancel")
def cancel(experiment_id: str):
    try: return ok(cancel_experiment(experiment_id), "已请求取消")
    except LookupError as exc: raise HTTPException(404, str(exc))


@router.delete("/experiments/{experiment_id}")
def remove(experiment_id: str, confirmed: bool = False):
    try: delete_experiment(experiment_id, confirmed); return ok({"id": experiment_id}, "实验已删除")
    except LookupError as exc: raise HTTPException(404, str(exc))
    except ValueError as exc: raise HTTPException(409, str(exc))


@router.get("/models")
def models(): return ok(list_models())


@router.get("/safnet/info")
def safnet_info(): return ok(structure_info())


@router.get("/safnet/samples")
def safnet_samples(limit: int = Query(100, ge=1, le=500)):
    with SessionLocal() as db:
        rows=list(db.scalars(select(SpatiotemporalSample).order_by(SpatiotemporalSample.forecast_time.desc()).limit(limit)))
        return ok([{"id":x.id,"sid":x.sid,"forecast_time":x.forecast_time.isoformat()+"Z","target_time":x.target_time.isoformat()+"Z","split":x.split,"shape":x.shape} for x in rows])


@router.post("/safnet/predict")
def predict_safnet(payload: SAFNetPredictRequest):
    try:return ok(safnet_predict(payload.model_id,payload.sample_id,payload.include_attention),"SAF-Net 历史回测完成")
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(422,str(exc))


@router.get("/comparison")
def comparison():
    rows = []
    for model in list_models():
        test = (model.get("metrics") or {}).get("test", {}).get("overall")
        if test: rows.append({"model_id": model["id"], "experiment_id": model["experiment_id"], "name": model["name"], "model_type": model["model_type"], **test})
    return ok(rows)


@router.post("/predict")
def predict(payload: BacktestRequest):
    try: return ok(historical_predict(payload.model_id, payload.typhoon_id, payload.forecast_time.replace(tzinfo=None)), "历史回测预测完成")
    except LookupError as exc: raise HTTPException(404, str(exc))
    except ValueError as exc: raise HTTPException(422, str(exc))


def _export_rows():
    rows=[]
    for item in list_experiments():
        overall=(item.get("metrics") or {}).get("test",{}).get("overall",{})
        rows.append({"实验ID":item["id"],"名称":item["name"],"模型":item["model_type"],"质量规则":item["quality_profile"],"状态":item["status"],"创建时间":item["created_at"],"测试样本":overall.get("sample_count"),"MAE":overall.get("mae"),"RMSE":overall.get("rmse"),"Bias":overall.get("bias"),"相对持续性改善%":overall.get("improvement_pct")})
    return rows


@router.get("/export/experiments")
def export_experiments(format: str = Query("csv", pattern="^(csv|xlsx)$")):
    rows=_export_rows(); headers=list(rows[0]) if rows else ["实验ID","名称","模型","状态"]
    if format=="csv":
        output=io.StringIO(); output.write("\ufeff"); writer=csv.DictWriter(output,fieldnames=headers); writer.writeheader(); writer.writerows(rows)
        return StreamingResponse(iter([output.getvalue().encode("utf-8")]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=experiments.csv"})
    book=Workbook(); sheet=book.active; sheet.title="实验记录"; sheet.append(headers)
    for row in rows: sheet.append([row.get(key) for key in headers])
    output=io.BytesIO(); book.save(output); output.seek(0)
    return StreamingResponse(output,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=experiments.xlsx"})
