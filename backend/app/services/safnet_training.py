"""SAF-Net 正式训练、权重管理、推理与注意力提取。"""
from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC,datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import torch
from sqlalchemy import select
from torch import nn
from torch.utils.data import DataLoader

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.era5 import SpatiotemporalSample
from backend.app.models.ml import EvaluationResult,ModelArtifact,PredictionRecord,TrainingExperiment
from backend.app.models.typhoon import TyphoonEvent
from backend.app.services.ml_metrics import evaluation_details
from backend.app.services.safnet_dataset import Normalization,SAFNetDataset,availability,fit_normalization,rows_for_split
from backend.app.services.safnet_model import SAFNet,SAFNetConfig,parameter_report
from backend.app.services.phase8_service import freeze_dataset

ACTIVE={"queued","preparing","training","evaluating"}
DEFAULTS={"epochs":50,"batch_size":16,"learning_rate":.001,"patience":8,"gradient_clip":1.0,"seed":42,"cnn_channels":[32,64],"time_embedding":96,"attention_heads":8,"attention_layers":1,"fusion_hidden":128,"dropout":.1,"time_features":1}
_executor=ThreadPoolExecutor(max_workers=settings.training_max_workers,thread_name_prefix="safnet")
_signals:dict[str,threading.Event]={};_lock=threading.RLock()


def _utc(value):return value.replace(tzinfo=UTC).isoformat().replace("+00:00","Z") if isinstance(value,datetime) else value
def _experiment_dict(row):return {c.name:_utc(getattr(row,c.name)) for c in TrainingExperiment.__table__.columns}
def _save(experiment_id,**values):
    with SessionLocal() as db:
        row=db.get(TrainingExperiment,experiment_id)
        if row:
            for key,value in values.items():setattr(row,key,value)
            db.commit()


def model_config(raw:dict|None=None)->SAFNetConfig:
    value={**DEFAULTS,**(raw or {})}
    config=SAFNetConfig(time_features=int(value["time_features"]),cnn_channels=tuple(map(int,value["cnn_channels"])),time_embedding=int(value["time_embedding"]),attention_heads=int(value["attention_heads"]),attention_layers=int(value["attention_layers"]),fusion_hidden=int(value["fusion_hidden"]),dropout=float(value["dropout"]));config.validate();return config


def structure_info(raw:dict|None=None)->dict:
    config=model_config(raw);model=SAFNet(config)
    return {"name":"SAF-Net","config":config.serializable(),"parameters":parameter_report(model),"input":{"spatial":["B",4,2,31,31],"temporal":["B",4,config.time_features]},"output":["B",1],"device":"cuda" if torch.cuda.is_available() else "cpu","pipeline":[{"name":"ERA5 空间输入","shape":"B×4×2×31×31"},{"name":"共享 CNN + 空间注意力","shape":f"B×4×{config.cnn_channels[-1]}"},{"name":"历史时序嵌入 + 多头注意力","shape":f"B×4×{config.time_embedding}"},{"name":"时空特征融合","shape":f"B×{config.fusion_hidden}"},{"name":"6 小时风速回归头","shape":"B×1"}],"availability":availability(),"attention_note":"注意力仅反映网络内部关注模式，不代表气象因果关系。"}


def create_experiment(payload:dict)->dict:
    state=availability()
    if not state["ready"]:raise ValueError(f"当前尚无可用的 ERA5 时空样本，SAF-Net 正式训练暂不可用。分组：{state['splits']}")
    values={**DEFAULTS,**(payload.get("config") or {})};config=model_config(values)
    values.update(config.serializable());values["epochs"]=max(1,min(int(values["epochs"]),300));values["batch_size"]=max(1,min(int(values["batch_size"]),128));values["patience"]=max(1,int(values["patience"]));values["learning_rate"]=float(values["learning_rate"])
    experiment_id=str(uuid4())
    with _lock,SessionLocal() as db:
        active=db.scalar(select(TrainingExperiment).where(TrainingExperiment.status.in_(ACTIVE)))
        if active:raise ValueError(f"已有训练任务运行中：{active.id}")
        row=TrainingExperiment(id=experiment_id,name=str(payload.get("name") or "SAF-Net 时空融合实验"),model_type="safnet",quality_profile="strict",status="queued",phase="queued",max_epochs=values["epochs"],config=values,seed=int(values["seed"]));db.add(row);db.commit();result=_experiment_dict(row)
    signal=threading.Event();_signals[experiment_id]=signal;_executor.submit(_run,experiment_id,signal);return result


def cancel(experiment_id:str):
    signal=_signals.get(experiment_id)
    if signal:signal.set()


def _seed(value:int):random.seed(value);np.random.seed(value);torch.manual_seed(value);torch.set_num_threads(settings.training_cpu_threads)
def _check(signal):
    if signal.is_set():raise InterruptedError("用户取消训练")


def _normalization(value:dict)->Normalization:return Normalization(tuple(value["wind_mean"]),tuple(value["wind_std"]),tuple(value["temporal_mean"]),tuple(value["temporal_std"]),float(value["target_mean"]),float(value["target_std"]))


def _predict(model,loader,device,normalization):
    predictions=[]
    model.eval()
    with torch.no_grad():
        for batch in loader:
            values=model(batch["wind"].to(device),batch["temporal"].to(device)).squeeze(-1).cpu().numpy()
            predictions.extend((values*normalization.target_std+normalization.target_mean).tolist())
    return np.asarray(predictions)


def _run(experiment_id,signal):
    started=time.perf_counter();artifact_dir=settings.model_dir/experiment_id
    try:
        _save(experiment_id,status="preparing",phase="validating_spatiotemporal_samples",started_at=datetime.now(UTC),progress=2)
        with SessionLocal() as db:row=db.get(TrainingExperiment,experiment_id);values=dict(row.config);name=row.name
        _seed(int(values["seed"]));groups={split:rows_for_split(split) for split in ("train","validation","test")}
        if not all(groups.values()):raise ValueError("训练、验证或测试时空样本为空")
        normalization=fit_normalization(groups["train"]);config=model_config(values);device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
        datasets={key:SAFNetDataset(rows,normalization) for key,rows in groups.items()};generator=torch.Generator().manual_seed(int(values["seed"]))
        loaders={key:DataLoader(ds,batch_size=int(values["batch_size"]),shuffle=key=="train",generator=generator if key=="train" else None) for key,ds in datasets.items()}
        model=SAFNet(config).to(device);optimizer=torch.optim.Adam(model.parameters(),lr=float(values["learning_rate"]));loss_fn=nn.MSELoss();best=float("inf");best_epoch=None;best_state=None;remaining=int(values["patience"]);curve=[]
        artifact_dir.mkdir(parents=True,exist_ok=False);state=availability();processing_version=groups["train"][0].processing_version;manifest=freeze_dataset(processing_version);version=manifest["dataset_version"];stats={key:{"sample_count":len(rows),"event_count":len({r.sid for r in rows})} for key,rows in groups.items()};stats["experiment_level"]=state["experiment_level"];stats["limitations"]=state["limitations"];stats["manifest_sha256"]=manifest["manifest_sha256"]
        _save(experiment_id,status="training",phase="training",progress=5,artifact_dir=str(artifact_dir),dataset_version=version,split_statistics=stats,device=str(device))
        for epoch in range(1,int(values["epochs"])+1):
            _check(signal);model.train();total=0.0
            for batch in loaders["train"]:
                _check(signal);optimizer.zero_grad();prediction=model(batch["wind"].to(device),batch["temporal"].to(device)).squeeze(-1);loss=loss_fn(prediction,batch["target"].to(device));loss.backward();nn.utils.clip_grad_norm_(model.parameters(),float(values["gradient_clip"]));optimizer.step();total+=loss.item()*len(prediction)
            model.eval();validation_total=0.0
            with torch.no_grad():
                for batch in loaders["validation"]:
                    prediction=model(batch["wind"].to(device),batch["temporal"].to(device)).squeeze(-1);validation_total+=loss_fn(prediction,batch["target"].to(device)).item()*len(prediction)
            train_loss=total/len(datasets["train"]);validation_loss=validation_total/len(datasets["validation"]);curve.append({"epoch":epoch,"train_loss":train_loss,"validation_loss":validation_loss})
            _save(experiment_id,current_epoch=epoch,progress=round(epoch/int(values["epochs"])*82+5,2),training_curve=curve)
            if validation_loss<best-1e-7:best=validation_loss;best_epoch=epoch;best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()};remaining=int(values["patience"])
            else:
                remaining-=1
                if remaining<=0:break
        if best_state is None:raise ValueError("训练未产生有效权重")
        model.load_state_dict(best_state);_check(signal);_save(experiment_id,status="evaluating",phase="evaluating",progress=90)
        metrics={}
        for split,rows in groups.items():
            evaluation_loader=DataLoader(datasets[split],batch_size=int(values["batch_size"]),shuffle=False)
            predicted=_predict(model,evaluation_loader,device,normalization);samples=[SimpleNamespace(sid=r.sid,season=r.forecast_time.year,forecast_time=r.forecast_time,target_time=r.target_time,target=r.target_wind,winds=(0,0,0,r.temporal_features[3])) for r in rows]
            metrics[split]=evaluation_details(samples,predicted)
        checkpoint={"state_dict":best_state,"config":config.serializable(),"normalization":normalization.serializable(),"format_version":1};model_path=artifact_dir/"safnet.pt";torch.save(checkpoint,model_path)
        checksum=hashlib.sha256(model_path.read_bytes()).hexdigest();metadata={"experiment_id":experiment_id,"model_type":"safnet","dataset_version":version,"experiment_level":state["experiment_level"],"limitations":state["limitations"],"config":config.serializable(),"normalization":normalization.serializable(),"parameters":parameter_report(model),"sha256":checksum,"best_epoch":best_epoch,"best_validation_loss":best,"training_seconds":time.perf_counter()-started,"python_version":__import__('sys').version,"pytorch_version":torch.__version__,"device":str(device),"seed":int(values["seed"]),"created_at":datetime.now(UTC).isoformat()}
        metadata_path=artifact_dir/"metadata.json";metadata_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        model_id=str(uuid4())
        with SessionLocal() as db:
            db.add(ModelArtifact(id=model_id,experiment_id=experiment_id,name=name,model_type="safnet",model_path=str(model_path),metadata_path=str(metadata_path),dataset_version=version,feature_names=["cma_wind_ms"],metrics=metrics))
            for split,detail in metrics.items():
                for kind,groups2 in {"overall":{"all":detail["overall"]},**detail["groups"]}.items():
                    for group,data in groups2.items():db.add(EvaluationResult(experiment_id=experiment_id,split=split,group_type=kind,group_value=str(group),sample_count=data["sample_count"],mae=data["mae"],rmse=data["rmse"],bias=data["bias"],persistence_mae=data.get("persistence_mae"),improvement_pct=data.get("improvement_pct")))
            row=db.get(TrainingExperiment,experiment_id);row.status="succeeded";row.phase="succeeded";row.progress=100;row.metrics=metrics;row.finished_at=datetime.now(UTC);db.commit()
    except InterruptedError as exc:_save(experiment_id,status="cancelled",phase="cancelled",error_message=str(exc),finished_at=datetime.now(UTC))
    except Exception as exc:_save(experiment_id,status="failed",phase="failed",error_message=f"{type(exc).__name__}: {exc}",finished_at=datetime.now(UTC))
    finally:_signals.pop(experiment_id,None)


def load_model(artifact:ModelArtifact)->tuple[SAFNet,Normalization,dict]:
    model_path=Path(artifact.model_path);metadata=json.loads(Path(artifact.metadata_path).read_text("utf-8"))
    if hashlib.sha256(model_path.read_bytes()).hexdigest()!=metadata["sha256"]:raise ValueError("SAF-Net 权重校验失败")
    checkpoint=torch.load(model_path,map_location="cpu",weights_only=True);config=model_config(checkpoint["config"]);model=SAFNet(config);model.load_state_dict(checkpoint["state_dict"],strict=True);model.eval()
    return model,_normalization(checkpoint["normalization"]),metadata


def _sample_tensors(sample:SpatiotemporalSample,normalization:Normalization):
    item=SAFNetDataset([sample],normalization)[0];return item["wind"].unsqueeze(0),item["temporal"].unsqueeze(0)


def predict(model_id:str,sample_id:str,include_attention:bool=False)->dict:
    with SessionLocal() as db:
        artifact=db.get(ModelArtifact,model_id);sample=db.get(SpatiotemporalSample,sample_id)
        if not artifact or artifact.model_type!="safnet":raise LookupError("SAF-Net 模型权重不存在")
        if not sample:raise LookupError("完整四时次 ERA5 样本不存在")
        event=db.get(TyphoonEvent,sample.typhoon_id);model,normalization,metadata=load_model(artifact);wind,temporal=_sample_tensors(sample,normalization)
        with torch.no_grad():prediction,attention=model(wind,temporal,return_attention=True)
        predicted=float(prediction.item()*normalization.target_std+normalization.target_mean);error=predicted-sample.target_wind
        record=PredictionRecord(id=str(uuid4()),model_id=model_id,typhoon_id=sample.typhoon_id,sid=sample.sid,forecast_time=sample.forecast_time,target_time=sample.target_time,predicted_wind=predicted,actual_wind=sample.target_wind,error=error,input_features={"spatiotemporal_sample_id":sample.id,"wind_field_ids":sample.wind_field_ids},quality_profile="strict");db.add(record);db.commit();db.refresh(record);db.refresh(sample);db.refresh(artifact)
        if event:db.refresh(event)
    result={"id":record.id,"sample_id":sample.id,"sid":sample.sid,"name":event.name if event else sample.sid,"forecast_time":_utc(sample.forecast_time),"target_time":_utc(sample.target_time),"predicted_wind":predicted,"actual_wind":sample.target_wind,"error":error,"model_id":model_id,"model_name":artifact.name,"model_type":"safnet","model_version":metadata["dataset_version"],"data_source":"NOAA IBTrACS CMA + Copernicus ERA5 U10/V10","config":metadata["config"],"status":"historical_backtest"}
    if include_attention:result["attention"]={"spatial":attention["spatial"].squeeze(0).squeeze(1).tolist(),"temporal":attention["temporal"].squeeze(0).tolist(),"note":"注意力仅反映网络内部关注模式，不代表气象因果关系。"}
    return result
