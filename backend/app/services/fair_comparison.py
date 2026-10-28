"""五模型在同一 ERA5 可用测试子集上的只读、公平推理。"""
from __future__ import annotations

from types import SimpleNamespace
import time

import numpy as np
import torch
from sqlalchemy import select
from torch.utils.data import DataLoader

from backend.app.db.database import SessionLocal
from backend.app.models.era5 import SpatiotemporalSample
from backend.app.models.ml import ModelArtifact
from backend.app.services.ml_metrics import evaluation_details
from backend.app.services.ml_training import _load_predictor
from backend.app.services.safnet_dataset import SAFNetDataset
from backend.app.services.safnet_training import load_model


def _metric(samples,predicted,seconds):
    detail=evaluation_details(samples,np.asarray(predicted,float))["overall"]
    return {**detail,"inference_seconds":round(seconds,6)}


def compare_common_test_set()->dict:
    with SessionLocal() as db:
        rows=list(db.scalars(select(SpatiotemporalSample).where(SpatiotemporalSample.split=="test").order_by(SpatiotemporalSample.forecast_time)))
        if not rows:return {"status":"unavailable","reason":"共同测试集为空","items":[]}
        artifacts=list(db.scalars(select(ModelArtifact).order_by(ModelArtifact.created_at.desc())));latest={}
        for artifact in artifacts:latest.setdefault(artifact.model_type,artifact)
        safnet_candidates=[x for x in artifacts if x.model_type=="safnet"]
        if safnet_candidates:
            latest["safnet"]=min(safnet_candidates,key=lambda x:((x.metrics or {}).get("validation",{}).get("overall",{}).get("mae",float("inf"))))
        samples=[SimpleNamespace(sid=r.sid,season=r.forecast_time.year,forecast_time=r.forecast_time,target_time=r.target_time,target=r.target_wind,winds=tuple(map(float,r.temporal_features[:4]))) for r in rows]
        items=[]
        for kind in ("persistence","ridge","lstm","gru"):
            artifact=latest.get(kind)
            if not artifact:continue
            _,predictor=_load_predictor(artifact);started=time.perf_counter();pred=[predictor(x.winds) for x in samples]
            items.append({"model_type":kind,"model_id":artifact.id,**_metric(samples,pred,time.perf_counter()-started)})
        artifact=latest.get("safnet")
        if artifact:
            model,norm,_=load_model(artifact);dataset=SAFNetDataset(rows,norm);started=time.perf_counter();pred=[]
            with torch.no_grad():
                for item in DataLoader(dataset,batch_size=16,shuffle=False):pred.extend((model(item["wind"],item["temporal"]).squeeze(-1).numpy()*norm.target_std+norm.target_mean).tolist())
            items.append({"model_type":"safnet","model_id":artifact.id,**_metric(samples,pred,time.perf_counter()-started)})
        persistence=next((x["mae"] for x in items if x["model_type"]=="persistence"),None)
        for item in items:item["improvement_pct"]=(persistence-item["mae"])/persistence*100 if persistence else None
        event_count=len({x.sid for x in rows});formal=event_count>=5 and len(rows)>=20 and len(items)==5
        return {"status":"formal" if formal else "experimental","formal_ranking_allowed":formal,"reason":None if formal else "共同测试集事件或样本不足，仅展示小样本试验结果，不作正式排名。","sample_ids":[x.id for x in rows],"sample_count":len(rows),"event_count":event_count,"label_source":"NOAA IBTrACS CMA_WIND（knots 转 m/s，严格 O/V 质量规则）","forecast_horizon_hours":6,"items":items}
