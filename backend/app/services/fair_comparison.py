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
from backend.app.services.phase8_service import event_cluster_bootstrap


def _metric(samples,predicted,seconds):
    detail=evaluation_details(samples,np.asarray(predicted,float))["overall"]
    return {**detail,"inference_seconds":round(seconds,6)}


def select_formal_safnet(artifacts):
    """Select by validation only and reject pre-final exploratory datasets."""
    candidates=[x for x in artifacts if x.model_type=="safnet" and str(x.dataset_version or "").startswith("era5-phase8-final-")]
    return min(candidates,key=lambda x:((x.metrics or {}).get("validation",{}).get("overall",{}).get("mae",float("inf")))) if candidates else None


def compare_common_test_set()->dict:
    with SessionLocal() as db:
        rows=list(db.scalars(select(SpatiotemporalSample).where(SpatiotemporalSample.split=="test",SpatiotemporalSample.processing_version=="spatiotemporal-v2").order_by(SpatiotemporalSample.forecast_time)))
        if not rows:return {"status":"unavailable","reason":"共同测试集为空","items":[]}
        artifacts=list(db.scalars(select(ModelArtifact).order_by(ModelArtifact.created_at.desc())));latest={}
        for artifact in artifacts:latest.setdefault(artifact.model_type,artifact)
        selected_safnet=select_formal_safnet(artifacts)
        if selected_safnet:latest["safnet"]=selected_safnet
        samples=[SimpleNamespace(sid=r.sid,season=r.forecast_time.year,forecast_time=r.forecast_time,target_time=r.target_time,target=r.target_wind,winds=tuple(map(float,r.temporal_features[:4]))) for r in rows]
        items=[]
        for kind in ("persistence","ridge","lstm","gru"):
            artifact=latest.get(kind)
            if not artifact:continue
            _,predictor=_load_predictor(artifact);started=time.perf_counter();pred=[predictor(x.winds) for x in samples]
            items.append({"model_type":kind,"model_id":artifact.id,**_metric(samples,pred,time.perf_counter()-started)})
        artifact=latest.get("safnet");safnet_points=[]
        if artifact:
            model,norm,_=load_model(artifact);dataset=SAFNetDataset(rows,norm);started=time.perf_counter();pred=[]
            with torch.no_grad():
                for item in DataLoader(dataset,batch_size=16,shuffle=False):pred.extend((model(item["wind"],item["temporal"]).squeeze(-1).numpy()*norm.target_std+norm.target_mean).tolist())
            items.append({"model_type":"safnet","model_id":artifact.id,**_metric(samples,pred,time.perf_counter()-started)})
            safnet_points=[{"sid":sample.sid,"actual":sample.target,"safnet":float(value),"persistence":float(sample.winds[-1])} for sample,value in zip(samples,pred)]
        persistence=next((x["mae"] for x in items if x["model_type"]=="persistence"),None)
        for item in items:item["improvement_pct"]=(persistence-item["mae"])/persistence*100 if persistence else None
        event_count=len({x.sid for x in rows});formal=event_count>=5 and len(rows)>=20 and len(items)==5
        selection=None
        if artifact:
            validation=(artifact.metrics or {}).get("validation",{}).get("overall",{})
            selection={"model_id":artifact.id,"experiment_id":artifact.experiment_id,"criterion":"minimum_validation_mae","validation_mae":validation.get("mae"),"dataset_version":artifact.dataset_version}
        bootstrap=event_cluster_bootstrap(safnet_points,"safnet","persistence") if safnet_points else {"reliable":False,"reason":"没有 SAF-Net 测试预测。"}
        return {"status":"formal" if formal else "experimental","formal_ranking_allowed":formal,"reason":None if formal else "共同测试集事件或样本不足，仅展示小样本试验结果，不作正式排名。","sample_ids":[x.id for x in rows],"sample_count":len(rows),"event_count":event_count,"label_source":"NOAA IBTrACS CMA_WIND（knots 转 m/s，严格 O/V 质量规则）","forecast_horizon_hours":6,"safnet_selection":selection,"bootstrap_safnet_minus_persistence":bootstrap,"items":items}
