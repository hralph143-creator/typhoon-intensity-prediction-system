"""第十阶段轻量多时效分位数网络与消融配置。"""
from __future__ import annotations

from dataclasses import asdict,dataclass

import torch
from torch import Tensor,nn
from torch.nn import functional as F

from backend.app.services.phase10_dataset import HORIZONS,QUANTILES
from backend.app.services.safnet_model import SpatialAttention,TemporalEncoder

VARIANTS=("history_only","spatial_only","cnn_average","cnn_temporal_attention","spatial_attention_simple","full_safnet")


@dataclass(frozen=True)
class Phase10Config:
    variant:str="full_safnet"
    channels:tuple[int,int]=(8,16)
    time_embedding:int=16
    attention_heads:int=4
    hidden:int=32
    dropout:float=.1

    def validate(self):
        if self.variant not in VARIANTS:raise ValueError(f"未知消融配置：{self.variant}")
        if self.time_embedding%self.attention_heads:raise ValueError("时间嵌入维度必须能被注意力头数整除")
        if min(self.channels)<=0 or self.hidden<=0 or not 0<=self.dropout<1:raise ValueError("模型配置无效")
    def serializable(self):
        result=asdict(self);result["channels"]=list(self.channels);return result


class WindEncoder(nn.Module):
    def __init__(self,channels:tuple[int,int],attention:bool):
        super().__init__();c1,c2=channels;self.features=nn.Sequential(nn.Conv2d(2,c1,3,padding=1),nn.ReLU(),nn.Conv2d(c1,c2,3,padding=1),nn.ReLU());self.attention=SpatialAttention() if attention else None;self.pool=nn.AdaptiveAvgPool2d(1);self.output_size=c2
    def forward(self,wind:Tensor)->tuple[Tensor,Tensor|None]:
        values=self.features(wind);weights=None
        if self.attention:values,weights=self.attention(values)
        return self.pool(values).flatten(1),weights


class OrderedQuantileHead(nn.Module):
    def __init__(self,input_size:int):super().__init__();self.output=nn.Linear(input_size,len(HORIZONS)*len(QUANTILES))
    def forward(self,values:Tensor)->Tensor:
        raw=self.output(values).reshape(-1,len(HORIZONS),len(QUANTILES));low=raw[...,0];median=low+F.softplus(raw[...,1]);high=median+F.softplus(raw[...,2]);return torch.stack((low,median,high),dim=-1)


class Phase10Net(nn.Module):
    def __init__(self,config:Phase10Config|None=None):
        super().__init__();self.config=config or Phase10Config();self.config.validate();v=self.config.variant;uses_spatial=v!="history_only";uses_attention=v in {"spatial_attention_simple","full_safnet"};self.wind_encoder=WindEncoder(self.config.channels,uses_attention) if uses_spatial else None
        self.temporal_attention=TemporalEncoder(1,self.config.time_embedding,self.config.attention_heads,1,self.config.dropout) if v in {"cnn_temporal_attention","full_safnet"} else None
        if v=="history_only":input_size=4
        elif v=="spatial_only":input_size=self.config.channels[-1]
        elif v=="cnn_average":input_size=self.config.channels[-1]+4
        elif v=="cnn_temporal_attention":input_size=self.config.time_embedding
        elif v=="spatial_attention_simple":input_size=self.config.channels[-1]+4
        else:input_size=self.config.channels[-1]+self.config.time_embedding
        self.fusion=nn.Sequential(nn.Linear(input_size,self.config.hidden),nn.LayerNorm(self.config.hidden),nn.GELU(),nn.Dropout(self.config.dropout));self.head=OrderedQuantileHead(self.config.hidden)

    def forward(self,wind:Tensor,temporal:Tensor,return_attention:bool=False):
        if wind.ndim!=5 or tuple(wind.shape[1:])!=(4,2,31,31):raise ValueError("空间输入必须为 (B,4,2,31,31)")
        if temporal.ndim!=3 or tuple(temporal.shape[1:])!=(4,1) or temporal.shape[0]!=wind.shape[0]:raise ValueError("时间输入必须为 (B,4,1)")
        v=self.config.variant;batch=wind.shape[0];spatial_attention=None;temporal_attention=None
        if self.wind_encoder:
            encoded,weights=self.wind_encoder(wind.reshape(batch*4,2,31,31));spatial=encoded.reshape(batch,4,-1)
            if weights is not None:spatial_attention=weights.reshape(batch,4,1,31,31)
        if self.temporal_attention:
            time_encoded,temporal_attention=self.temporal_attention(temporal)
        if v=="history_only":features=temporal.flatten(1)
        elif v=="spatial_only":features=spatial.mean(dim=1)
        elif v in {"cnn_average","spatial_attention_simple"}:features=torch.cat((spatial.mean(dim=1),temporal.flatten(1)),dim=1)
        elif v=="cnn_temporal_attention":features=time_encoded[:,-1]
        else:features=torch.cat((spatial.mean(dim=1),time_encoded[:,-1]),dim=1)
        prediction=self.head(self.fusion(features))
        if return_attention:return prediction,{"spatial":spatial_attention,"temporal":temporal_attention}
        return prediction


def pinball_loss(prediction:Tensor,target:Tensor,mask:Tensor,quantiles:tuple[float,...]=QUANTILES)->Tensor:
    if prediction.ndim!=3 or prediction.shape[1:]!=(len(HORIZONS),len(quantiles)):raise ValueError("分位数输出形状错误")
    if target.shape!=prediction.shape[:2] or mask.shape!=target.shape:raise ValueError("目标或掩码形状错误")
    errors=target.unsqueeze(-1)-prediction;q=torch.tensor(quantiles,device=prediction.device,dtype=prediction.dtype);loss=torch.maximum(q*errors,(q-1)*errors);valid=mask.unsqueeze(-1).expand_as(loss)
    if not valid.any():raise ValueError("当前批次没有有效目标")
    return loss[valid].mean()


def parameter_count(model:nn.Module)->int:return sum(value.numel() for value in model.parameters() if value.requires_grad)
