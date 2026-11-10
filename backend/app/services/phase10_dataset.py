"""第十阶段多时效数据集：复用冻结 ERA5 输入，只扩展真实未来标签。"""
from __future__ import annotations

import hashlib
import json
from collections import Counter,defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import torch
from sqlalchemy import select
from torch.utils.data import Dataset

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.era5 import SpatiotemporalSample
from backend.app.services.ml_dataset import STRICT_FLAGS,latest_main_observations

HORIZONS=(6,12,18,24)
QUANTILES=(.1,.5,.9)
PROCESSING_VERSION="multi-horizon-v1"


@dataclass(frozen=True)
class MultiHorizonSample:
    id:str
    row:SpatiotemporalSample
    targets:tuple[float|None,...]

    @property
    def mask(self)->tuple[bool,...]:return tuple(value is not None for value in self.targets)


@dataclass(frozen=True)
class MultiNormalization:
    wind_mean:tuple[float,float]
    wind_std:tuple[float,float]
    temporal_mean:tuple[float,...]
    temporal_std:tuple[float,...]
    target_mean:tuple[float,...]
    target_std:tuple[float,...]

    def serializable(self)->dict:return {key:list(value) for key,value in self.__dict__.items()}


def _read_input(row:SpatiotemporalSample)->tuple[np.ndarray,np.ndarray]:
    path=Path(row.local_path)
    if not path.is_file():raise ValueError(f"ERA5 样本文件不存在：{row.id}")
    with np.load(path,allow_pickle=False) as item:
        wind=np.asarray(item["wind"],np.float32);raw=np.asarray(item["temporal"],np.float32)
    temporal=raw.reshape(4,1) if raw.shape==(4,) else raw[:4].reshape(4,1)
    if wind.shape!=(4,2,31,31) or temporal.shape!=(4,1):raise ValueError(f"样本形状错误：{row.id}")
    if not np.isfinite(wind).all() or not np.isfinite(temporal).all():raise ValueError(f"样本包含非有限值：{row.id}")
    return wind,temporal


def build_multi_horizon_samples(db=None)->list[MultiHorizonSample]:
    own=db is None;db=db or SessionLocal()
    try:
        rows=list(db.scalars(select(SpatiotemporalSample).where(SpatiotemporalSample.processing_version=="spatiotemporal-v2").order_by(SpatiotemporalSample.forecast_time)))
        observations=defaultdict(dict)
        for observation,event in latest_main_observations(db):observations[event.id][observation.observation_time]=observation
        result=[]
        for row in rows:
            targets=[]
            for hours in HORIZONS:
                observation=observations[row.typhoon_id].get(row.forecast_time+timedelta(hours=hours))
                valid=observation and observation.cma_wind_ms is not None and observation.cma_iflag in STRICT_FLAGS
                targets.append(float(observation.cma_wind_ms) if valid else None)
            if targets[0] is None or abs(targets[0]-row.target_wind)>1e-5:raise ValueError(f"冻结 6 小时标签不一致：{row.id}")
            result.append(MultiHorizonSample(row.id,row,tuple(targets)))
        split_sids={name:{item.row.sid for item in result if item.row.split==name} for name in ("train","validation","test")}
        if any(split_sids[a]&split_sids[b] for a,b in (("train","validation"),("train","test"),("validation","test"))):raise ValueError("多时效数据存在 SID 跨分区泄漏")
        return result
    finally:
        if own:db.close()


def dataset_version(samples:list[MultiHorizonSample]|None=None)->str:
    samples=build_multi_horizon_samples() if samples is None else samples
    payload=[{"id":x.id,"split":x.row.split,"forecast_time":x.row.forecast_time.isoformat(),"targets":x.targets} for x in samples]
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return f"{PROCESSING_VERSION}-{digest[:16]}"


def freeze_manifest(samples:list[MultiHorizonSample]|None=None)->dict:
    samples=build_multi_horizon_samples() if samples is None else samples;version=dataset_version(samples)
    payload={"dataset_version":version,"processing_version":PROCESSING_VERSION,"horizons":list(HORIZONS),"source_processing_version":"spatiotemporal-v2","samples":[{"id":x.id,"sid":x.row.sid,"split":x.row.split,"forecast_time":x.row.forecast_time.isoformat()+"Z","targets":list(x.targets),"mask":list(x.mask)} for x in samples]}
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode();payload["manifest_sha256"]=hashlib.sha256(encoded).hexdigest()
    folder=settings.era5_processed_dir/"phase10";folder.mkdir(parents=True,exist_ok=True);path=folder/"multi-horizon-manifest.json";path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    return {**payload,"path":str(path)}


def fit_normalization(samples:list[MultiHorizonSample])->MultiNormalization:
    if not samples:raise ValueError("训练集为空")
    winds=[];temporals=[];targets=[[] for _ in HORIZONS]
    for sample in samples:
        wind,temporal=_read_input(sample.row);winds.append(wind);temporals.append(temporal)
        for index,value in enumerate(sample.targets):
            if value is not None:targets[index].append(value)
    wind=np.stack(winds);temporal=np.stack(temporals);wm=wind.mean(axis=(0,1,3,4));ws=wind.std(axis=(0,1,3,4));tm=temporal.mean(axis=(0,1));ts=temporal.std(axis=(0,1))
    means=[float(np.mean(values)) for values in targets];stds=[float(np.std(values)) or 1.0 for values in targets]
    return MultiNormalization(tuple(map(float,wm)),tuple(map(float,np.where(ws<1e-6,1,ws))),tuple(map(float,tm)),tuple(map(float,np.where(ts<1e-6,1,ts))),tuple(means),tuple(stds))


class MultiHorizonDataset(Dataset):
    def __init__(self,samples:list[MultiHorizonSample],normalization:MultiNormalization):self.samples=samples;self.normalization=normalization
    def __len__(self):return len(self.samples)
    def __getitem__(self,index):
        sample=self.samples[index];wind,temporal=_read_input(sample.row);n=self.normalization
        wind=(wind-np.asarray(n.wind_mean)[None,:,None,None])/np.asarray(n.wind_std)[None,:,None,None]
        temporal=(temporal-np.asarray(n.temporal_mean)[None,:])/np.asarray(n.temporal_std)[None,:]
        mask=np.asarray(sample.mask,bool);raw=np.asarray([0 if x is None else x for x in sample.targets],np.float32);target=(raw-np.asarray(n.target_mean,np.float32))/np.asarray(n.target_std,np.float32);target=np.where(mask,target,0)
        return {"wind":torch.tensor(wind,dtype=torch.float32),"temporal":torch.tensor(temporal,dtype=torch.float32),"target":torch.tensor(target,dtype=torch.float32),"mask":torch.tensor(mask,dtype=torch.bool),"sample_id":sample.id,"sid":sample.row.sid,"split":sample.row.split}


def audit_multi_horizon(samples:list[MultiHorizonSample]|None=None)->dict:
    samples=build_multi_horizon_samples() if samples is None else samples;version=dataset_version(samples);splits={}
    for split in ("train","validation","test"):
        rows=[x for x in samples if x.row.split==split];horizon={}
        for index,hours in enumerate(HORIZONS):
            values=[x.targets[index] for x in rows if x.targets[index] is not None];events={x.row.sid for x in rows if x.targets[index] is not None}
            horizon[str(hours)]={"samples":len(values),"events":len(events),"minimum":min(values) if values else None,"maximum":max(values) if values else None,"mean":float(np.mean(values)) if values else None,"std":float(np.std(values)) if values else None}
        splits[split]={"samples":len(rows),"events":len({x.row.sid for x in rows}),"horizons":horizon}
    split_sids={name:{x.row.sid for x in samples if x.row.split==name} for name in splits};intersections={f"{a}_{b}":sorted(split_sids[a]&split_sids[b]) for a,b in (("train","validation"),("train","test"),("validation","test"))}
    winds=[];input_targets=[]
    for sample in samples:
        wind,_=_read_input(sample.row);winds.append(wind)
        if sample.targets[0] is not None:input_targets.append((sample.row.temporal_features[3],sample.targets[0]))
    counts=Counter(x.row.sid for x in samples);ordered=sorted(samples,key=lambda x:(x.row.sid,x.row.forecast_time));adjacent=sum(a.row.sid==b.row.sid and b.row.forecast_time-a.row.forecast_time==timedelta(hours=6) for a,b in zip(ordered,ordered[1:]))
    ri=sum(x.targets[3] is not None and x.targets[3]-x.row.temporal_features[3]>=15.4 for x in samples);rw=sum(x.targets[3] is not None and x.targets[3]-x.row.temporal_features[3]<=-15.4 for x in samples)
    array=np.stack(winds) if winds else None
    correlation=float(np.corrcoef(np.asarray(input_targets).T)[0,1]) if len(input_targets)>1 else None
    return {"dataset_version":version,"processing_version":PROCESSING_VERSION,"horizons":list(HORIZONS),"quantiles":list(QUANTILES),"total_samples":len(samples),"total_events":len(counts),"splits":splits,"sid_intersections":intersections,"no_sid_leakage":all(not value for value in intersections.values()),"future_inputs_used":False,"frozen_6h_compatible":all(x.targets[0] is not None and abs(x.targets[0]-x.row.target_wind)<1e-5 for x in samples),"wind":{"minimum":float(array.min()) if array is not None else None,"maximum":float(array.max()) if array is not None else None,"finite_ratio":float(np.isfinite(array).mean()) if array is not None else None,"shape":[4,2,31,31]},"input_target_6h_correlation":correlation,"rapid_intensification_24h":ri,"rapid_weakening_24h":rw,"adjacent_window_ratio":adjacent/max(1,len(samples)-1),"largest_event_share":max(counts.values())/len(samples) if counts else None,"event_sample_counts":dict(sorted(counts.items())),"formal_by_horizon":{str(h):splits["validation"]["horizons"][str(h)]["events"]>=5 and splits["test"]["horizons"][str(h)]["events"]>=5 for h in HORIZONS}}
