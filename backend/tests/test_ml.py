from datetime import datetime, timedelta
import time
import threading

import numpy as np
import pytest
import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.migrations import migrate
from backend.app.models.typhoon import SourceFile, TyphoonEvent, TyphoonObservation
from backend.app.services import ml_dataset, ml_training
from backend.app.services.ml_dataset import IntensitySample, build_samples, split_statistics
from backend.app.services.ml_metrics import regression_metrics
from backend.app.services.ml_models import RecurrentRegressor


@pytest.fixture
def sequence_db(tmp_path, monkeypatch):
    engine=create_engine("sqlite:///"+(tmp_path/"ml.db").as_posix()); migrate(engine); sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(ml_dataset,"SessionLocal",sessions)
    with sessions() as db:
        source=SourceFile(source="ibtracs",original_filename="real.csv",local_path=str(tmp_path/"real.csv"),sha256="a"*64,file_size=1,version="v04r01",status="imported");db.add(source);db.flush()
        for index,season in enumerate((2020,2022,2024)):
            start=datetime(season,7,1); event=TyphoonEvent(source="ibtracs",sid=f"SID{season}",season=season,name=f"T{season}",first_observation=start,last_observation=start+timedelta(hours=30),observation_count=6);db.add(event);db.flush()
            for step in range(6):
                db.add(TyphoonObservation(typhoon_id=event.id,observation_time=start+timedelta(hours=step*6),latitude=10,longitude=120,basin="WP",track_type="MAIN",cma_wind=30+step,cma_wind_ms=(30+step)*0.514444,cma_iflag="O",iflag="OOO",wind_unit="knots",quality_flags=[],raw_values={"IFLAG":"OOO"},source_file_id=source.id,row_hash=f"{season}-{step}"))
        db.commit()
    yield sessions
    engine.dispose()


def test_valid_windows_are_grouped_by_sid_and_split(sequence_db):
    samples=build_samples("strict")
    assert len(samples)==6
    assert {row.split for row in samples}=={"train","validation","test"}
    assert all(row.target_time-row.forecast_time==timedelta(hours=6) for row in samples)
    assert split_statistics(samples)["no_sid_leakage"] is True


def test_audit_reports_history_and_future_label_counts(sequence_db):
    ml_dataset.audit_data.cache_clear() if hasattr(ml_dataset.audit_data,"cache_clear") else None
    result=ml_dataset.audit_data()
    assert result["strict_window_audit"]["complete_history_windows"]==9
    assert result["strict_window_audit"]["future_6h_labels"]==6
    assert result["event_sequence_lengths"]=={"SID2020":6,"SID2022":6,"SID2024":6}


def test_missing_and_interpolated_values_are_filtered(sequence_db):
    with sequence_db() as db:
        row=db.query(TyphoonObservation).filter(TyphoonObservation.typhoon_id==1).order_by(TyphoonObservation.observation_time).offset(2).first();row.cma_iflag="P";db.commit()
    assert not [row for row in build_samples("strict") if row.sid=="SID2020"]
    assert len([row for row in build_samples("extended") if row.sid=="SID2020"])==2


def test_missing_value_is_never_zero_filled(sequence_db):
    with sequence_db() as db:
        row=db.query(TyphoonObservation).filter(TyphoonObservation.typhoon_id==1).first();row.cma_wind_ms=None;db.commit()
    assert len([row for row in build_samples("extended") if row.sid=="SID2020"])==1


def test_no_future_information_in_features():
    sample=IntensitySample("S",1,2020,datetime(2020,1,1,18),datetime(2020,1,2), (1,2,3,4),99,"strict","train")
    assert sample.ridge_features==[1,2,3,4,1,2]
    assert 99 not in sample.ridge_features


def test_ridge_uses_training_scaler_and_predicts(tmp_path):
    base=datetime(2020,1,1)
    train=[IntensitySample(f"S{i}",i,2020,base,base+timedelta(hours=6),(10+i,11+i,12+i,13+i),14+i,"strict","train") for i in range(8)]
    validation=[IntensitySample("V",20,2022,base,base+timedelta(hours=6),(40,41,42,43),44,"strict","validation")]
    path,config,curve,predict=ml_training._train_ridge(train,validation,{"ridge_alphas":[.1,1]},tmp_path,threading.Event())
    bundle=__import__('joblib').load(path)
    assert bundle["scaler"].mean_[0]==pytest.approx(np.mean([row.winds[0] for row in train]))
    assert np.isfinite(predict(validation)[0])
    assert config["alpha"] in {.1,1}
    assert len(curve)==2


def test_persistence_and_regression_metrics():
    result=regression_metrics([10,20],[10,18],[10,20])
    assert result["mae"]==1
    assert result["rmse"]==pytest.approx(np.sqrt(2))
    assert result["bias"]==-1
    assert result["improvement_pct"] is None


@pytest.mark.parametrize("kind",["lstm","gru"])
def test_recurrent_forward_and_reload(kind,tmp_path):
    model=RecurrentRegressor(kind,hidden_size=8); values=torch.randn(5,4,1); expected=model(values)
    path=tmp_path/f"{kind}.pt";torch.save(model.state_dict(),path); loaded=RecurrentRegressor(kind,hidden_size=8);loaded.load_state_dict(torch.load(path,weights_only=True))
    assert expected.shape==(5,)
    assert torch.allclose(expected,loaded(values))


def test_training_failure_is_persisted(monkeypatch):
    from backend.app.db.database import init_db
    init_db(); monkeypatch.setattr(ml_training,"build_samples",lambda profile:[])
    experiment=ml_training.create_experiment({"model_type":"persistence","quality_profile":"strict","name":"failure-test"})
    deadline=time.time()+10
    while time.time()<deadline:
        result=ml_training.get_experiment(experiment["id"])
        if result["status"] not in ml_training.ACTIVE: break
        time.sleep(.05)
    assert result["status"]=="failed"
    assert "无样本" in result["error_message"]


def test_historical_prediction_api_error():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    with TestClient(app) as client:
        response=client.post("/api/ml/predict",json={"model_id":"missing","typhoon_id":1,"forecast_time":"2024-01-01T00:00:00Z"})
    assert response.status_code==404
    assert response.json()["success"] is False
