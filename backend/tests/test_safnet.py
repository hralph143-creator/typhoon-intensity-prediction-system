from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient

from backend.app.db.database import SessionLocal,init_db
from backend.app.main import app
from backend.app.models.ml import TrainingExperiment
from backend.app.services.safnet_dataset import SAFNetDataset,fit_normalization
from backend.app.services.safnet_model import SAFNet,SAFNetConfig,SpatialAttention,SpatialEncoder,TemporalEncoder,parameter_report
from backend.app.services.safnet_training import create_experiment,model_config,structure_info


@pytest.fixture(scope="module",autouse=True)
def initialized_database():
    init_db()


def row(tmp_path:Path,sid="S1",split="train",offset=0,bad_shape=False):
    path=tmp_path/f"{sid}-{offset}.npz";wind=np.random.default_rng(offset).normal(size=(4,2,31,31)).astype("float32")
    if bad_shape:wind=wind[:,:,:30]
    temporal=np.asarray([10,12,14,16,2,4],dtype="float32");np.savez_compressed(path,wind=wind,temporal=temporal,target=np.float32(18))
    start=datetime(2020,1,1)+timedelta(hours=offset)
    return SimpleNamespace(id=f"{sid}-{offset}",sid=sid,split=split,local_path=str(path),forecast_time=start,target_time=start+timedelta(hours=6),target_wind=18.0,temporal_features=temporal.tolist(),typhoon_id=1,wind_field_ids=[1,2,3,4],shape=[4,2,31,31],quality_report={"finite":True})


def test_safnet_forward_and_attention_shapes():
    model=SAFNet();wind=torch.randn(2,4,2,31,31);temporal=torch.randn(2,4,1)
    prediction,attention=model(wind,temporal,return_attention=True)
    assert prediction.shape==(2,1) and torch.isfinite(prediction).all()
    assert attention["spatial"].shape==(2,4,1,31,31)
    assert attention["temporal"].shape==(2,1,8,4,4)
    assert torch.all((attention["spatial"]>=0)&(attention["spatial"]<=1))


@pytest.mark.parametrize("batch",[1,2,5])
def test_different_batch_sizes(batch):
    assert SAFNet()(torch.randn(batch,4,2,31,31),torch.randn(batch,4,1)).shape==(batch,1)


def test_individual_modules_and_gradients():
    spatial=SpatialEncoder();features,weights=spatial(torch.randn(3,2,31,31));assert features.shape==(3,64) and weights.shape==(3,1,31,31)
    temporal=TemporalEncoder(1);encoded,attention=temporal(torch.randn(3,4,1));assert encoded.shape==(3,4,96) and attention.shape==(3,1,8,4,4)
    model=SAFNet();prediction=model(torch.randn(2,4,2,31,31),torch.randn(2,4,1));prediction.square().mean().backward()
    gradients=[p.grad for p in model.parameters() if p.requires_grad];assert all(g is not None and torch.isfinite(g).all() for g in gradients)


def test_optimizer_updates_parameters():
    torch.manual_seed(4);model=SAFNet(SAFNetConfig(cnn_channels=(4,8),time_embedding=16,attention_heads=4,fusion_hidden=16,dropout=0));optimizer=torch.optim.Adam(model.parameters(),lr=.001)
    before=next(model.parameters()).detach().clone();loss=(model(torch.randn(2,4,2,31,31),torch.randn(2,4,1)).squeeze()-torch.tensor([1.,2.])).square().mean();optimizer.zero_grad();loss.backward();optimizer.step()
    assert not torch.equal(before,next(model.parameters()).detach())


def test_invalid_configuration_and_inputs():
    with pytest.raises(ValueError,match="整除"):SAFNet(SAFNetConfig(time_embedding=95,attention_heads=8))
    model=SAFNet()
    with pytest.raises(ValueError,match="空间输入"):model(torch.randn(2,4,2,30,31),torch.randn(2,4,1))
    bad=torch.randn(2,4,1);bad[0,0,0]=float("nan")
    with pytest.raises(ValueError,match="NaN"):model(torch.randn(2,4,2,31,31),bad)
    with pytest.raises(ValueError,match="空间注意力"):SpatialAttention()(torch.randn(2,3,4))


def test_parameter_report_is_exact_and_lightweight():
    model=SAFNet();report=parameter_report(model)
    assert report["total"]==sum(p.numel() for p in model.parameters())
    assert report["total"]==report["trainable"]
    assert 100_000<report["total"]<300_000
    assert sum(report["modules"].values())==report["total"]


def test_dataset_reads_four_times_and_train_only_normalization(tmp_path):
    train=[row(tmp_path,"TRAIN",offset=i*6) for i in range(2)];normalization=fit_normalization(train);dataset=SAFNetDataset(train,normalization);item=dataset[0]
    assert item["wind"].shape==(4,2,31,31) and item["temporal"].shape==(4,1) and item["target"].dtype==torch.float32
    assert normalization.target_mean==18 and normalization.target_std==1


def test_dataset_rejects_corrupt_shape_and_future_mismatch(tmp_path):
    bad=row(tmp_path,bad_shape=True)
    with pytest.raises(ValueError,match="空间形状"):SAFNetDataset([bad])[0]
    good=row(tmp_path,"TIME");good.target_time=good.forecast_time+timedelta(hours=12)
    with pytest.raises(ValueError,match="6 小时"):SAFNetDataset([good])[0]


def test_checkpoint_roundtrip_is_identical(tmp_path):
    config=SAFNetConfig(cnn_channels=(4,8),time_embedding=16,attention_heads=4,fusion_hidden=16,dropout=0);model=SAFNet(config).eval();wind=torch.randn(1,4,2,31,31);temporal=torch.randn(1,4,1)
    expected=model(wind,temporal);path=tmp_path/"smoke.pt";torch.save({"state_dict":model.state_dict(),"config":config.serializable()},path);checkpoint=torch.load(path,weights_only=True);loaded=SAFNet(model_config(checkpoint["config"]));loaded.load_state_dict(checkpoint["state_dict"],strict=True);loaded.eval()
    assert torch.equal(expected,loaded(wind,temporal))


def test_no_era5_data_rejects_formal_training_without_db_record():
    with SessionLocal() as db:before=db.query(TrainingExperiment).count()
    with pytest.raises(ValueError,match="暂不可用"):create_experiment({"model_type":"safnet","config":{}})
    with SessionLocal() as db:assert db.query(TrainingExperiment).count()==before


def test_structure_and_api_report_truthful_unavailable_state():
    info=structure_info();assert info["input"]["spatial"]==["B",4,2,31,31] and info["availability"]["total"]==0
    with TestClient(app) as client:
        response=client.get("/api/ml/safnet/info");assert response.status_code==200 and response.json()["data"]["availability"]["ready"] is False
        rejected=client.post("/api/ml/experiments",json={"model_type":"safnet","quality_profile":"strict","config":{}});assert rejected.status_code==409
        missing=client.post("/api/ml/safnet/predict",json={"model_id":"missing","sample_id":"missing"});assert missing.status_code==404
