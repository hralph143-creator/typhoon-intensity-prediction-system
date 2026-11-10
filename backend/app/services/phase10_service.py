"""第十阶段真实消融、多时效概率训练、评价与推理。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import time
from collections import defaultdict
from datetime import UTC,datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import torch
from sklearn.linear_model import Ridge
from sqlalchemy import select
from torch import nn
from torch.utils.data import DataLoader

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.ml import ModelArtifact,TrainingExperiment
from backend.app.services.fair_comparison import compare_common_test_set
from backend.app.services.phase10_dataset import HORIZONS,QUANTILES,MultiHorizonDataset,MultiHorizonSample,MultiNormalization,audit_multi_horizon,build_multi_horizon_samples,fit_normalization,freeze_manifest
from backend.app.services.phase10_model import VARIANTS,Phase10Config,Phase10Net,parameter_count,pinball_loss

SEEDS=(42,3407,2026)
DEFAULT_EPOCHS=30


def _summary_path()->Path:return settings.era5_processed_dir/"phase10"/"phase10-summary.json"
def _utc_now()->datetime:return datetime.now(UTC)
def _seed(value:int):random.seed(value);np.random.seed(value);torch.manual_seed(value);torch.set_num_threads(settings.training_cpu_threads)
def _normalization(value:dict)->MultiNormalization:return MultiNormalization(*(tuple(value[key]) for key in ("wind_mean","wind_std","temporal_mean","temporal_std","target_mean","target_std")))


def _split(samples,split):return [x for x in samples if x.row.split==split]


def _physical(prediction:np.ndarray,normalization:MultiNormalization)->np.ndarray:
    return prediction*np.asarray(normalization.target_std)[None,:,None]+np.asarray(normalization.target_mean)[None,:,None]


def _arrays(samples:list[MultiHorizonSample]):
    actual=np.asarray([[np.nan if value is None else value for value in x.targets] for x in samples],float);mask=np.isfinite(actual);return actual,mask


def _metric(actual,predicted,mask)->dict:
    values=[];by={}
    for index,hours in enumerate(HORIZONS):
        valid=mask[:,index];error=predicted[valid,index]-actual[valid,index]
        item={"sample_count":int(valid.sum()),"mae":float(np.mean(np.abs(error))),"rmse":float(np.sqrt(np.mean(error**2))),"bias":float(np.mean(error))};by[str(hours)]=item;values.extend(error.tolist())
    errors=np.asarray(values,float);return {"overall":{"sample_count":len(values),"mae":float(np.mean(np.abs(errors))),"rmse":float(np.sqrt(np.mean(errors**2))),"bias":float(np.mean(errors))},"by_horizon":by}


def _probability_metric(actual,quantiles,mask)->dict:
    by={};pinballs=[]
    for index,hours in enumerate(HORIZONS):
        valid=mask[:,index];truth=actual[valid,index];values=quantiles[valid,index];low,median,high=values.T;coverage=float(np.mean((truth>=low)&(truth<=high)));width=float(np.mean(high-low));loss=[]
        for q,column in zip(QUANTILES,values.T):
            error=truth-column;loss.extend(np.maximum(q*error,(q-1)*error).tolist())
        item={"sample_count":len(truth),"coverage_p10_p90":coverage,"mean_interval_width":width,"pinball_loss":float(np.mean(loss)),"quantile_crossings":int(np.sum((low>median)|(median>high)))};by[str(hours)]=item;pinballs.extend(loss)
    return {"overall_pinball_loss":float(np.mean(pinballs)),"by_horizon":by}


def _predict_quantiles(model,loader,normalization):
    output=[];model.eval()
    with torch.no_grad():
        for batch in loader:output.append(model(batch["wind"],batch["temporal"]).cpu().numpy())
    return _physical(np.concatenate(output),normalization)


def _persist_run(run,config,normalization,checkpoint,metadata,validation_metrics):
    experiment_id=run["experiment_id"];folder=Path(run["artifact_dir"]);folder.mkdir(parents=True,exist_ok=False);model_path=folder/"phase10.pt";torch.save(checkpoint,model_path);checksum=hashlib.sha256(model_path.read_bytes()).hexdigest();metadata={**metadata,"sha256":checksum};metadata_path=folder/"metadata.json";metadata_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8");model_id=str(uuid4())
    now=_utc_now();split_stats=run["split_statistics"]
    with SessionLocal() as db:
        db.add(TrainingExperiment(id=experiment_id,name=run["name"],model_type="mh_safnet",quality_profile="strict",status="succeeded",phase="validation_selected_candidate",progress=100,current_epoch=metadata["best_epoch"],max_epochs=run["epochs"],config={**config.serializable(),"experiment_category":"ablation","horizons":list(HORIZONS),"quantiles":list(QUANTILES)},dataset_version=run["dataset_version"],split_statistics=split_stats,training_curve=run["curve"],metrics={"validation":validation_metrics},device="cpu",seed=run["seed"],artifact_dir=str(folder),created_at=now,started_at=now,finished_at=now))
        db.commit()
        db.add(ModelArtifact(id=model_id,experiment_id=experiment_id,name=run["name"],model_type="mh_safnet",model_path=str(model_path),metadata_path=str(metadata_path),dataset_version=run["dataset_version"],feature_names=["u10","v10","cma_wind_t-18h","cma_wind_t-12h","cma_wind_t-6h","cma_wind_t"],metrics={"validation":validation_metrics}))
        db.commit()
    return model_id,str(model_path),str(metadata_path),checksum


def _train_variant(samples:list[MultiHorizonSample],normalization:MultiNormalization,variant:str,seed:int,version:str,epochs:int):
    _seed(seed);config=Phase10Config(variant=variant);groups={name:_split(samples,name) for name in ("train","validation","test")};datasets={name:MultiHorizonDataset(rows,normalization) for name,rows in groups.items()};generator=torch.Generator().manual_seed(seed);train_loader=DataLoader(datasets["train"],batch_size=16,shuffle=True,generator=generator);val_loader=DataLoader(datasets["validation"],batch_size=32,shuffle=False);model=Phase10Net(config);optimizer=torch.optim.Adam(model.parameters(),lr=.002,weight_decay=1e-4);best=float("inf");best_state=None;best_epoch=0;patience=6;curve=[];started=time.perf_counter()
    for epoch in range(1,epochs+1):
        model.train();losses=[];gradients=[]
        for batch in train_loader:
            optimizer.zero_grad();prediction=model(batch["wind"],batch["temporal"]);loss=pinball_loss(prediction,batch["target"],batch["mask"]);loss.backward();gradient=float(nn.utils.clip_grad_norm_(model.parameters(),2.0));optimizer.step();losses.append(float(loss.detach()));gradients.append(gradient)
        model.eval();validation=[]
        with torch.no_grad():
            for batch in val_loader:validation.append(float(pinball_loss(model(batch["wind"],batch["temporal"]),batch["target"],batch["mask"])))
        train_loss=float(np.mean(losses));val_loss=float(np.mean(validation));curve.append({"epoch":epoch,"train_loss":train_loss,"validation_loss":val_loss,"gradient_norm":float(np.mean(gradients))})
        if val_loss<best-1e-6:best=val_loss;best_epoch=epoch;best_state={key:value.detach().cpu().clone() for key,value in model.state_dict().items()};patience=6
        else:
            patience-=1
            if patience<=0:break
    if best_state is None:raise ValueError("训练没有产生有效权重")
    model.load_state_dict(best_state);validation_quantiles=_predict_quantiles(model,val_loader,normalization);actual,mask=_arrays(groups["validation"]);validation_metrics={**_metric(actual,validation_quantiles[:,:,1],mask),"probability":_probability_metric(actual,validation_quantiles,mask)};experiment_id=str(uuid4());folder=settings.model_dir/experiment_id;stats={name:{"samples":len(rows),"events":len({x.row.sid for x in rows}),"labels":{str(h):sum(x.targets[i] is not None for x in rows) for i,h in enumerate(HORIZONS)}} for name,rows in groups.items()};run={"experiment_id":experiment_id,"name":f"第十阶段 {variant} seed={seed}","artifact_dir":str(folder),"seed":seed,"epochs":epochs,"curve":curve,"dataset_version":version,"split_statistics":stats};checkpoint={"format_version":2,"state_dict":best_state,"config":config.serializable(),"normalization":normalization.serializable(),"horizons":HORIZONS,"quantiles":QUANTILES};metadata={"experiment_id":experiment_id,"variant":variant,"seed":seed,"best_epoch":best_epoch,"best_validation_loss":best,"training_seconds":time.perf_counter()-started,"parameters":parameter_count(model),"selection_split":"validation","test_used_for_selection":False,"dataset_version":version,"normalization":normalization.serializable()};model_id,model_path,metadata_path,checksum=_persist_run(run,config,normalization,checkpoint,metadata,validation_metrics)
    reload_model=Phase10Net(config);saved=torch.load(model_path,map_location="cpu",weights_only=True);reload_model.load_state_dict(saved["state_dict"]);reloaded=_predict_quantiles(reload_model,val_loader,normalization);reload_difference=float(np.max(np.abs(reloaded-validation_quantiles)))
    return {"experiment_id":experiment_id,"model_id":model_id,"model_path":model_path,"metadata_path":metadata_path,"checksum":checksum,"variant":variant,"seed":seed,"parameters":parameter_count(model),"best_epoch":best_epoch,"training_seconds":metadata["training_seconds"],"validation":validation_metrics,"curve":curve,"reload_max_difference":reload_difference}


class _GRU(nn.Module):
    def __init__(self):super().__init__();self.gru=nn.GRU(1,16,batch_first=True);self.head=nn.Linear(16,len(HORIZONS))
    def forward(self,x):return self.head(self.gru(x)[0][:,-1])


def _baseline_results(samples,normalization):
    groups={name:_split(samples,name) for name in ("train","validation","test")};result={}
    for split in ("validation","test"):
        actual,mask=_arrays(groups[split]);persistence=np.asarray([[x.row.temporal_features[3]]*len(HORIZONS) for x in groups[split]],float);result.setdefault("persistence",{})[split]=_metric(actual,persistence,mask)
    train_features=np.asarray([list(x.row.temporal_features[:4])+[x.row.temporal_features[3]-x.row.temporal_features[2],x.row.temporal_features[3]-x.row.temporal_features[1]] for x in groups["train"]],float)
    for split in ("validation","test"):
        features=np.asarray([list(x.row.temporal_features[:4])+[x.row.temporal_features[3]-x.row.temporal_features[2],x.row.temporal_features[3]-x.row.temporal_features[1]] for x in groups[split]],float);actual,mask=_arrays(groups[split]);pred=np.zeros_like(actual)
        for index in range(len(HORIZONS)):
            y=np.asarray([x.targets[index] for x in groups["train"] if x.targets[index] is not None]);valid=np.asarray([x.targets[index] is not None for x in groups["train"]]);pred[:,index]=Ridge(alpha=1).fit(train_features[valid],y).predict(features)
        result.setdefault("ridge",{})[split]=_metric(actual,pred,mask)
    _seed(42);train_ds=MultiHorizonDataset(groups["train"],normalization);loaders={name:DataLoader(MultiHorizonDataset(rows,normalization),batch_size=16,shuffle=name=="train",generator=torch.Generator().manual_seed(42) if name=="train" else None) for name,rows in groups.items()};model=_GRU();optimizer=torch.optim.Adam(model.parameters(),lr=.005);best=float("inf");state=None;patience=8
    for _ in range(60):
        model.train()
        for batch in loaders["train"]:
            optimizer.zero_grad();prediction=model(batch["temporal"]);valid=batch["mask"];loss=((prediction-batch["target"])[valid]**2).mean();loss.backward();optimizer.step()
        model.eval();values=[]
        with torch.no_grad():
            for batch in loaders["validation"]:
                prediction=model(batch["temporal"]);valid=batch["mask"];values.append(float(((prediction-batch["target"])[valid]**2).mean()))
        loss=float(np.mean(values))
        if loss<best-1e-6:best=loss;state={k:v.detach().clone() for k,v in model.state_dict().items()};patience=8
        else:
            patience-=1
            if patience<=0:break
    model.load_state_dict(state)
    for split in ("validation","test"):
        predictions=[]
        with torch.no_grad():
            for batch in loaders[split]:predictions.append(model(batch["temporal"]).numpy())
        values=np.concatenate(predictions)*np.asarray(normalization.target_std)+np.asarray(normalization.target_mean);actual,mask=_arrays(groups[split]);result.setdefault("gru",{})[split]=_metric(actual,values,mask)
    legacy=next((x for x in compare_common_test_set().get("items",[]) if x["model_type"]=="safnet"),None);result["legacy_safnet"]={"test_6h":legacy}
    return result


def _bootstrap(samples,candidate,persistence,iterations=1000):
    grouped=defaultdict(list)
    for index,sample in enumerate(samples):grouped[sample.row.sid].append(index)
    events=sorted(grouped);rng=np.random.default_rng(20261031);result={}
    actual,mask=_arrays(samples)
    for h_index,hours in enumerate(HORIZONS):
        estimates=[]
        for _ in range(iterations):
            indices=[index for event in rng.choice(events,len(events),replace=True) for index in grouped[event]];valid=mask[indices,h_index];truth=actual[indices,h_index][valid];estimates.append(float(np.mean(np.abs(candidate[indices,h_index][valid]-truth))-np.mean(np.abs(persistence[indices,h_index][valid]-truth))))
        values=np.asarray(estimates);result[str(hours)]={"estimate":float(np.mean(values)),"ci95":[float(np.quantile(values,.025)),float(np.quantile(values,.975))],"iterations":iterations,"resampling_unit":"typhoon_event","events":len(events)}
    return result


def run_phase10_experiments(force:bool=False,epochs:int=DEFAULT_EPOCHS)->dict:
    path=_summary_path()
    if path.is_file() and not force:return json.loads(path.read_text("utf-8"))
    samples=build_multi_horizon_samples();audit=audit_multi_horizon(samples);manifest=freeze_manifest(samples);version=audit["dataset_version"];normalization=fit_normalization(_split(samples,"train"));runs=[]
    for variant in VARIANTS:
        for seed in SEEDS:runs.append(_train_variant(samples,normalization,variant,seed,version,epochs))
    selected=[]
    for variant in VARIANTS:selected.append(min((x for x in runs if x["variant"]==variant),key=lambda x:x["validation"]["overall"]["mae"]))
    groups={name:_split(samples,name) for name in ("validation","test")};test_loader=DataLoader(MultiHorizonDataset(groups["test"],normalization),batch_size=32,shuffle=False);actual,mask=_arrays(groups["test"])
    for run in selected:
        checkpoint=torch.load(run["model_path"],map_location="cpu",weights_only=True);config=Phase10Config(**{**checkpoint["config"],"channels":tuple(checkpoint["config"]["channels"])});model=Phase10Net(config);model.load_state_dict(checkpoint["state_dict"]);quantiles=_predict_quantiles(model,test_loader,normalization);run["test"]={**_metric(actual,quantiles[:,:,1],mask),"probability":_probability_metric(actual,quantiles,mask)}
        with SessionLocal() as db:
            experiment=db.get(TrainingExperiment,run["experiment_id"]);artifact=db.get(ModelArtifact,run["model_id"]);experiment.metrics={"validation":run["validation"],"test":run["test"]};experiment.phase="succeeded_selected_by_validation";artifact.metrics=experiment.metrics;db.commit()
    candidate=min(selected,key=lambda x:x["validation"]["overall"]["mae"]);checkpoint=torch.load(candidate["model_path"],map_location="cpu",weights_only=True);config=Phase10Config(**{**checkpoint["config"],"channels":tuple(checkpoint["config"]["channels"])});model=Phase10Net(config);model.load_state_dict(checkpoint["state_dict"]);candidate_quantiles=_predict_quantiles(model,test_loader,normalization);persistence=np.asarray([[x.row.temporal_features[3]]*len(HORIZONS) for x in groups["test"]],float);baselines=_baseline_results(samples,normalization);bootstrap=_bootstrap(groups["test"],candidate_quantiles[:,:,1],persistence)
    seed_stability={variant:{"validation_mae_mean":float(np.mean([x["validation"]["overall"]["mae"] for x in runs if x["variant"]==variant])),"validation_mae_std":float(np.std([x["validation"]["overall"]["mae"] for x in runs if x["variant"]==variant]))} for variant in VARIANTS}
    summary={"generated_at":_utc_now().isoformat().replace("+00:00","Z"),"dataset_version":version,"manifest_sha256":manifest["manifest_sha256"],"selection_rule":"minimum mean validation MAE across 6/12/18/24h; test set evaluated only after selection","test_used_for_selection":False,"audit":audit,"normalization":normalization.serializable(),"baselines":baselines,"runs":runs,"selected_ablations":selected,"selected_candidate":{"variant":candidate["variant"],"seed":candidate["seed"],"experiment_id":candidate["experiment_id"],"model_id":candidate["model_id"],"model_path":candidate["model_path"],"validation":candidate["validation"],"test":candidate["test"]},"candidate_test_predictions":[{"sample_id":sample.id,"sid":sample.row.sid,"forecast_time":sample.row.forecast_time.isoformat()+"Z","actual":list(sample.targets),"p10":candidate_quantiles[index,:,0].tolist(),"p50":candidate_quantiles[index,:,1].tolist(),"p90":candidate_quantiles[index,:,2].tolist()} for index,sample in enumerate(groups["test"])],"bootstrap_candidate_minus_persistence":bootstrap,"diagnostics":{"seed_stability":seed_stability,"reload_max_difference":max(x["reload_max_difference"] for x in runs),"normalization_fit_split":"train","best_epoch_selection_split":"validation","test_evaluations_per_selected_ablation":1,"limitations":["样本仅覆盖32个独立事件","24小时训练标签少于6小时标签","ERA5输入只有U10/V10","历史回测不构成实时业务预报"]}}
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8");return summary


def _phase10_summary_raw()->dict:
    path=_summary_path()
    if not path.is_file():return {"available":False,"message":"第十阶段实验尚未运行","audit":audit_multi_horizon()}
    return {"available":True,**json.loads(path.read_text("utf-8"))}


def phase10_summary()->dict:
    """公开快照不返回本机模型与元数据的绝对路径。"""
    summary=_phase10_summary_raw()
    if not summary.get("available"):return summary
    def clean(value):
        if isinstance(value,dict):return {key:clean(item) for key,item in value.items() if key not in {"model_path","metadata_path","artifact_dir"}}
        if isinstance(value,list):return [clean(item) for item in value]
        return value
    return clean(summary)


def phase10_samples()->list[dict]:return [{"id":x.id,"sid":x.row.sid,"split":x.row.split,"forecast_time":x.row.forecast_time.isoformat()+"Z","actual":list(x.targets),"mask":list(x.mask)} for x in build_multi_horizon_samples()]


def phase10_predict(sample_id:str)->dict:
    summary=_phase10_summary_raw()
    if not summary.get("available"):raise ValueError(summary["message"])
    sample=next((x for x in build_multi_horizon_samples() if x.id==sample_id),None)
    if not sample:raise LookupError("多时效样本不存在")
    candidate=summary["selected_candidate"];checkpoint=torch.load(candidate["model_path"],map_location="cpu",weights_only=True);raw=checkpoint["config"];config=Phase10Config(**{**raw,"channels":tuple(raw["channels"])});model=Phase10Net(config);model.load_state_dict(checkpoint["state_dict"]);normalization=_normalization(checkpoint["normalization"]);loader=DataLoader(MultiHorizonDataset([sample],normalization),batch_size=1);batch=next(iter(loader))
    with torch.no_grad():prediction,attention=model(batch["wind"],batch["temporal"],return_attention=True)
    values=_physical(prediction.numpy(),normalization)[0]
    return {"sample_id":sample.id,"sid":sample.row.sid,"forecast_time":sample.row.forecast_time.isoformat()+"Z","horizons":list(HORIZONS),"p10":values[:,0].tolist(),"p50":values[:,1].tolist(),"p90":values[:,2].tolist(),"actual":list(sample.targets),"model_id":candidate["model_id"],"model_variant":candidate["variant"],"seed":candidate["seed"],"dataset_version":summary["dataset_version"],"data_source":"NOAA IBTrACS CMA + Copernicus ERA5 U10/V10","historical_backtest":True,"attention_available":attention["spatial"] is not None or attention["temporal"] is not None}


def phase10_csv()->bytes:
    summary=phase10_summary();output=io.StringIO();writer=csv.writer(output);writer.writerow(["sample_id","sid","forecast_time","horizon_hours","actual","p10","p50","p90"])
    for row in summary.get("candidate_test_predictions",[]):
        for index,hours in enumerate(HORIZONS):writer.writerow([row["sample_id"],row["sid"],row["forecast_time"],hours,row["actual"][index],row["p10"][index],row["p50"][index],row["p90"][index]])
    return ("\ufeff"+output.getvalue()).encode("utf-8")
