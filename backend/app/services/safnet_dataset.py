"""从第四阶段追溯记录惰性加载 SAF-Net 标准样本。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import torch
from sqlalchemy import select
from torch.utils.data import Dataset

from backend.app.db.database import SessionLocal
from backend.app.models.era5 import SpatiotemporalSample


@dataclass(frozen=True)
class Normalization:
    wind_mean: tuple[float,float]
    wind_std: tuple[float,float]
    temporal_mean: tuple[float,...]
    temporal_std: tuple[float,...]
    target_mean: float
    target_std: float

    def serializable(self)->dict:return {key:list(value) if isinstance(value,tuple) else value for key,value in self.__dict__.items()}


def rows_for_split(split:str)->list[SpatiotemporalSample]:
    with SessionLocal() as db:return list(db.scalars(select(SpatiotemporalSample).where(SpatiotemporalSample.split==split).order_by(SpatiotemporalSample.forecast_time)))


def availability()->dict:
    groups={name:rows_for_split(name) for name in ("train","validation","test")}
    sids={name:{row.sid for row in rows} for name,rows in groups.items()}
    intersections={f"{a}_{b}":sorted(sids[a]&sids[b]) for i,a in enumerate(sids) for b in list(sids)[i+1:]}
    return {"total":sum(map(len,groups.values())),"splits":{name:len(rows) for name,rows in groups.items()},"sid_intersections":intersections,"no_sid_leakage":all(not x for x in intersections.values()),"ready":all(groups.values())}


def _read(row:SpatiotemporalSample)->tuple[np.ndarray,np.ndarray,np.float32]:
    if list(row.shape or []) != [4,2,31,31]:raise ValueError(f"元数据空间形状错误：{row.shape}")
    if len(row.wind_field_ids or []) != 4:raise ValueError("样本必须追溯到四个单时次风场")
    if (row.quality_report or {}).get("finite") is False:raise ValueError("样本质量报告标记为非有限值")
    path=Path(row.local_path)
    if not path.is_file():raise ValueError(f"样本文件不存在：{row.id}")
    try:
        with np.load(path,allow_pickle=False) as item:
            wind=np.asarray(item["wind"],np.float32);raw=np.asarray(item["temporal"],np.float32);target=np.float32(item["target"])
    except Exception as exc:raise ValueError(f"样本文件损坏：{row.id}") from exc
    temporal=raw.reshape(4,1) if raw.shape==(4,) else raw[:4].reshape(4,1) if raw.shape==(6,) else raw
    if wind.shape!=(4,2,31,31):raise ValueError(f"空间形状错误：{wind.shape}")
    if temporal.ndim!=2 or temporal.shape[0]!=4:raise ValueError(f"时间形状错误：{temporal.shape}")
    if row.target_time-row.forecast_time!=timedelta(hours=6):raise ValueError("目标时刻必须为起报后 6 小时")
    if not np.isfinite(wind).all() or not np.isfinite(temporal).all() or not np.isfinite(target):raise ValueError("样本包含 NaN 或 Inf")
    return wind,temporal,target


def fit_normalization(rows:list[SpatiotemporalSample])->Normalization:
    if not rows:raise ValueError("训练集为空，无法拟合标准化参数")
    winds=[];temporals=[];targets=[]
    for row in rows:
        wind,temporal,target=_read(row);winds.append(wind);temporals.append(temporal);targets.append(target)
    wind=np.stack(winds);temporal=np.stack(temporals);target=np.asarray(targets,np.float32)
    wm=wind.mean(axis=(0,1,3,4));ws=wind.std(axis=(0,1,3,4));tm=temporal.mean(axis=(0,1));ts=temporal.std(axis=(0,1))
    ws=np.where(ws<1e-6,1,ws);ts=np.where(ts<1e-6,1,ts);target_std=float(target.std()) or 1.0
    return Normalization(tuple(map(float,wm)),tuple(map(float,ws)),tuple(map(float,tm)),tuple(map(float,ts)),float(target.mean()),target_std)


class SAFNetDataset(Dataset):
    def __init__(self,rows:list[SpatiotemporalSample],normalization:Normalization|None=None):self.rows=rows;self.normalization=normalization
    def __len__(self):return len(self.rows)
    def __getitem__(self,index):
        row=self.rows[index];wind,temporal,target=_read(row)
        if self.normalization:
            n=self.normalization;wind=(wind-np.asarray(n.wind_mean)[None,:,None,None])/np.asarray(n.wind_std)[None,:,None,None]
            temporal=(temporal-np.asarray(n.temporal_mean)[None,:])/np.asarray(n.temporal_std)[None,:];target=np.float32((target-n.target_mean)/n.target_std)
        return {"wind":torch.tensor(wind,dtype=torch.float32),"temporal":torch.tensor(temporal,dtype=torch.float32),"target":torch.tensor(target,dtype=torch.float32),"sample_id":row.id,"sid":row.sid,"forecast_time":row.forecast_time.isoformat(),"target_time":row.target_time.isoformat(),"split":row.split}
