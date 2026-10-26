"""SAF-Net：共享 CNN、空间注意力、时间多头注意力与特征融合。"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class SAFNetConfig:
    time_features: int = 1
    cnn_channels: tuple[int, int] = (32, 64)
    time_embedding: int = 96
    attention_heads: int = 8
    attention_layers: int = 1
    fusion_hidden: int = 128
    dropout: float = 0.1

    def validate(self) -> None:
        if self.time_features < 1: raise ValueError("time_features 必须大于 0")
        if len(self.cnn_channels) != 2 or min(self.cnn_channels) < 1: raise ValueError("cnn_channels 必须包含两个正整数")
        if self.time_embedding < 1 or self.attention_heads < 1: raise ValueError("时间嵌入维度和注意力头数必须大于 0")
        if self.time_embedding % self.attention_heads: raise ValueError("time_embedding 必须能被 attention_heads 整除")
        if self.attention_layers < 1: raise ValueError("attention_layers 必须大于 0")
        if not 0 <= self.dropout < 1: raise ValueError("dropout 必须位于 [0,1)")

    def serializable(self) -> dict:
        value=asdict(self);value["cnn_channels"]=list(self.cnn_channels);return value


class SpatialAttention(nn.Module):
    def __init__(self, kernel_size: int = 7):
        super().__init__()
        if kernel_size not in {3,7}: raise ValueError("空间注意力卷积核仅支持 3 或 7")
        self.conv=nn.Conv2d(2,1,kernel_size,padding=kernel_size//2,bias=False)

    def forward(self, features: Tensor) -> tuple[Tensor,Tensor]:
        if features.ndim!=4: raise ValueError("空间注意力输入必须为 (B,C,H,W)")
        descriptor=torch.cat((features.mean(dim=1,keepdim=True),features.amax(dim=1,keepdim=True)),dim=1)
        weights=torch.sigmoid(self.conv(descriptor))
        return features*weights,weights


class SpatialEncoder(nn.Module):
    def __init__(self, channels: tuple[int,int]=(32,64)):
        super().__init__();c1,c2=channels
        self.features=nn.Sequential(nn.Conv2d(2,c1,3,padding=1,bias=False),nn.BatchNorm2d(c1),nn.ReLU(),nn.Conv2d(c1,c2,3,padding=1,bias=False),nn.BatchNorm2d(c2),nn.ReLU())
        self.attention=SpatialAttention();self.pool=nn.AdaptiveAvgPool2d(1);self.output_size=c2

    def forward(self, wind:Tensor)->tuple[Tensor,Tensor]:
        if wind.ndim!=4 or wind.shape[1]!=2:raise ValueError("单时次风场必须为 (B,2,H,W)")
        weighted,attention=self.attention(self.features(wind))
        return self.pool(weighted).flatten(1),attention


class TemporalAttentionBlock(nn.Module):
    def __init__(self,d_model:int,heads:int,dropout:float):
        super().__init__();self.norm1=nn.LayerNorm(d_model);self.norm2=nn.LayerNorm(d_model)
        self.attention=nn.MultiheadAttention(d_model,heads,dropout=dropout,batch_first=True)
        self.feed_forward=nn.Sequential(nn.Linear(d_model,d_model*2),nn.GELU(),nn.Dropout(dropout),nn.Linear(d_model*2,d_model),nn.Dropout(dropout))
        self.dropout=nn.Dropout(dropout)

    def forward(self,values:Tensor)->tuple[Tensor,Tensor]:
        normalized=self.norm1(values)
        attended,weights=self.attention(normalized,normalized,normalized,need_weights=True,average_attn_weights=False)
        values=values+self.dropout(attended);values=values+self.feed_forward(self.norm2(values))
        return values,weights


class TemporalEncoder(nn.Module):
    def __init__(self,input_features:int,d_model:int=96,heads:int=8,layers:int=1,dropout:float=.1,max_steps:int=4):
        super().__init__()
        if d_model%heads:raise ValueError("d_model 必须能被 heads 整除")
        self.embedding=nn.Linear(input_features,d_model);self.position=nn.Parameter(torch.zeros(1,max_steps,d_model))
        nn.init.normal_(self.position,std=.02)
        self.blocks=nn.ModuleList([TemporalAttentionBlock(d_model,heads,dropout) for _ in range(layers)])
        self.output_norm=nn.LayerNorm(d_model);self.max_steps=max_steps

    def forward(self,values:Tensor)->tuple[Tensor,Tensor]:
        if values.ndim!=3 or values.shape[1]!=self.max_steps:raise ValueError(f"时间输入必须为 (B,{self.max_steps},F)")
        encoded=self.embedding(values)+self.position[:,:values.shape[1]];weights=[]
        for block in self.blocks:encoded,attention=block(encoded);weights.append(attention)
        return self.output_norm(encoded),torch.stack(weights,dim=1)


class SpatiotemporalFusion(nn.Module):
    def __init__(self,spatial_size:int,temporal_size:int,hidden:int,dropout:float):
        super().__init__();self.spatial_projection=nn.Linear(spatial_size,temporal_size);self.time_score=nn.Linear(temporal_size,1)
        self.fusion=nn.Sequential(nn.Linear(temporal_size*2,hidden),nn.LayerNorm(hidden),nn.GELU(),nn.Dropout(dropout))
        self.head=nn.Sequential(nn.Linear(hidden,max(16,hidden//2)),nn.GELU(),nn.Linear(max(16,hidden//2),1))

    def forward(self,spatial:Tensor,temporal:Tensor)->Tensor:
        if spatial.ndim!=3 or temporal.ndim!=3 or spatial.shape[:2]!=temporal.shape[:2]:raise ValueError("空间与时间特征的 Batch/时间维度不一致")
        spatial=self.spatial_projection(spatial)
        spatial_weights=torch.softmax(self.time_score(spatial),dim=1)
        spatial_context=(spatial*spatial_weights).sum(dim=1);temporal_context=temporal[:,-1]
        return self.head(self.fusion(torch.cat((spatial_context,temporal_context),dim=-1)))


class SAFNet(nn.Module):
    def __init__(self,config:SAFNetConfig|None=None):
        super().__init__();self.config=config or SAFNetConfig();self.config.validate()
        self.spatial_encoder=SpatialEncoder(self.config.cnn_channels)
        self.temporal_encoder=TemporalEncoder(self.config.time_features,self.config.time_embedding,self.config.attention_heads,self.config.attention_layers,self.config.dropout)
        self.fusion=SpatiotemporalFusion(self.spatial_encoder.output_size,self.config.time_embedding,self.config.fusion_hidden,self.config.dropout)

    def forward(self,wind:Tensor,temporal:Tensor,return_attention:bool=False):
        if wind.ndim!=5 or tuple(wind.shape[1:])!=(4,2,31,31):raise ValueError("空间输入必须为 (B,4,2,31,31)")
        if temporal.ndim!=3 or temporal.shape[0]!=wind.shape[0] or temporal.shape[1]!=4 or temporal.shape[2]!=self.config.time_features:raise ValueError(f"时间输入必须为 (B,4,{self.config.time_features})")
        if not torch.isfinite(wind).all() or not torch.isfinite(temporal).all():raise ValueError("模型输入包含 NaN 或 Inf")
        batch=wind.shape[0];features,spatial_attention=self.spatial_encoder(wind.reshape(batch*4,2,31,31))
        spatial=features.reshape(batch,4,-1);spatial_attention=spatial_attention.reshape(batch,4,1,31,31)
        temporal_encoded,temporal_attention=self.temporal_encoder(temporal)
        prediction=self.fusion(spatial,temporal_encoded)
        if return_attention:return prediction,{"spatial":spatial_attention,"temporal":temporal_attention}
        return prediction


def parameter_report(model:SAFNet)->dict:
    def count(module):return sum(value.numel() for value in module.parameters())
    return {"total":count(model),"trainable":sum(v.numel() for v in model.parameters() if v.requires_grad),"modules":{"spatial_encoder":count(model.spatial_encoder),"temporal_encoder":count(model.temporal_encoder),"fusion_and_head":count(model.fusion)}}
