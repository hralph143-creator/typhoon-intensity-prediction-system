"""真实模型训练、持久化、评估和历史回测推理。"""
from __future__ import annotations

import json
import os
import random
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
import torch
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler
from sqlalchemy import delete, select
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.ml import EvaluationResult, ModelArtifact, PredictionRecord, TrainingExperiment
from backend.app.models.typhoon import TyphoonEvent, TyphoonObservation
from backend.app.services.ml_dataset import FEATURE_NAMES, build_samples, dataset_version, split_statistics
from backend.app.services.ml_metrics import evaluation_details
from backend.app.services.ml_models import RecurrentRegressor

ACTIVE = {"queued", "preparing", "training", "evaluating"}
DEFAULTS = {"epochs": 40, "batch_size": 64, "learning_rate": 0.003, "hidden_size": 16, "num_layers": 1, "dropout": 0.0, "patience": 7, "gradient_clip": 1.0, "seed": 42}
_executor = ThreadPoolExecutor(max_workers=settings.training_max_workers, thread_name_prefix="training")
_lock = threading.RLock()
_signals: dict[str, threading.Event] = {}


def _utc(value):
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value


def experiment_dict(row: TrainingExperiment) -> dict:
    return {column.name: _utc(getattr(row, column.name)) for column in TrainingExperiment.__table__.columns}


def _save(experiment_id: str, **fields):
    with SessionLocal() as db:
        row = db.get(TrainingExperiment, experiment_id)
        if row:
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()


def recover_training_jobs():
    with SessionLocal() as db:
        for row in db.scalars(select(TrainingExperiment).where(TrainingExperiment.status.in_(ACTIVE))):
            row.status = "interrupted"; row.phase = "interrupted"; row.finished_at = datetime.now(UTC)
            row.error_message = "应用上次退出时训练未完成，请新建实验。"
        db.commit()


def create_experiment(payload: dict) -> dict:
    model_type = str(payload.get("model_type", "")).lower()
    if model_type == "safnet":
        from backend.app.services.safnet_training import create_experiment as create_safnet_experiment
        return create_safnet_experiment(payload)
    if model_type not in {"persistence", "ridge", "lstm", "gru"}:
        raise ValueError("模型必须为 persistence、ridge、lstm 或 gru")
    quality = payload.get("quality_profile", "strict")
    if quality not in {"strict", "extended"}:
        raise ValueError("质量配置必须为 strict 或 extended")
    config = {**DEFAULTS, **(payload.get("config") or {})}
    config["epochs"] = max(1, min(int(config["epochs"]), 300))
    config["batch_size"] = max(8, min(int(config["batch_size"]), 512))
    experiment_id = str(uuid4())
    with _lock, SessionLocal() as db:
        active = db.scalar(select(TrainingExperiment).where(TrainingExperiment.status.in_(ACTIVE)))
        if active:
            raise ValueError(f"已有训练任务运行中：{active.id}")
        row = TrainingExperiment(id=experiment_id, name=str(payload.get("name") or f"{model_type.upper()} 历史回测"), model_type=model_type, quality_profile=quality, status="queued", phase="queued", max_epochs=0 if model_type in {"persistence", "ridge"} else config["epochs"], config=config, seed=int(config["seed"]))
        db.add(row); db.commit(); result = experiment_dict(row)
        signal = threading.Event(); _signals[experiment_id] = signal
        _executor.submit(_run, experiment_id, signal)
        return result


def cancel_experiment(experiment_id: str) -> dict:
    with SessionLocal() as db:
        existing = db.get(TrainingExperiment, experiment_id)
        if not existing: raise LookupError("实验不存在")
        is_safnet = existing.model_type == "safnet"
    if is_safnet:
        from backend.app.services.safnet_training import cancel as cancel_safnet
        cancel_safnet(experiment_id)
    with _lock:
        signal = _signals.get(experiment_id)
        if signal: signal.set()
    with SessionLocal() as db:
        row = db.get(TrainingExperiment, experiment_id)
        if not row: raise LookupError("实验不存在")
        if row.status in ACTIVE:
            row.cancel_requested = True; db.commit()
        return experiment_dict(row)


def _seed(seed: int):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.set_num_threads(settings.training_cpu_threads)


def _check(signal):
    if signal.is_set():
        raise InterruptedError("用户取消训练")


def _arrays(samples, kind):
    if kind == "ridge":
        return np.asarray([row.ridge_features for row in samples], dtype=np.float32)
    return np.asarray([row.winds for row in samples], dtype=np.float32)[..., None]


def _train_ridge(train, validation, config, artifact_dir, signal):
    scaler = StandardScaler().fit(_arrays(train, "ridge"))
    x_train = scaler.transform(_arrays(train, "ridge")); y_train = np.asarray([row.target for row in train])
    x_val = scaler.transform(_arrays(validation, "ridge")); y_val = np.asarray([row.target for row in validation])
    candidates = config.get("ridge_alphas", [0.01, 0.1, 1.0, 10.0, 100.0])
    trials = []
    for alpha in candidates:
        _check(signal); model = Ridge(alpha=float(alpha)).fit(x_train, y_train)
        score = float(mean_absolute_error(y_val, model.predict(x_val)))
        trials.append({"alpha": float(alpha), "validation_mae": score, "model": model})
    best = min(trials, key=lambda item: item["validation_mae"])
    path = artifact_dir / "ridge.joblib"; joblib.dump({"model": best["model"], "scaler": scaler}, path)
    curve = [{"alpha": row["alpha"], "validation_mae": row["validation_mae"]} for row in trials]
    return path, {"alpha": best["alpha"]}, curve, lambda rows: best["model"].predict(scaler.transform(_arrays(rows, "ridge")))


def _train_deep(kind, train, validation, config, artifact_dir, signal, experiment_id):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_values = _arrays(train, kind); mean = float(train_values.mean()); std = float(train_values.std()) or 1.0
    def tensors(rows):
        x = torch.tensor((_arrays(rows, kind) - mean) / std, dtype=torch.float32)
        y = torch.tensor((np.asarray([row.target for row in rows], dtype=np.float32) - mean) / std)
        return x, y
    tx, ty = tensors(train); vx, vy = tensors(validation)
    loader = DataLoader(TensorDataset(tx, ty), batch_size=int(config["batch_size"]), shuffle=True, generator=torch.Generator().manual_seed(int(config["seed"])))
    model = RecurrentRegressor(kind, hidden_size=int(config["hidden_size"]), num_layers=int(config["num_layers"]), dropout=float(config["dropout"])).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(config["learning_rate"])); loss_fn = nn.MSELoss()
    best_loss = float("inf"); best_state = None; remaining = int(config["patience"]); curve = []
    for epoch in range(1, int(config["epochs"]) + 1):
        _check(signal); model.train(); total = 0.0
        for x, y in loader:
            _check(signal); x=x.to(device); y=y.to(device); optimizer.zero_grad(); loss=loss_fn(model(x), y); loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(config["gradient_clip"])); optimizer.step(); total += loss.item() * len(x)
        train_loss = total / len(train); model.eval()
        with torch.no_grad(): val_loss = float(loss_fn(model(vx.to(device)), vy.to(device)).item())
        curve.append({"epoch": epoch, "train_loss": train_loss, "validation_loss": val_loss})
        _save(experiment_id, current_epoch=epoch, progress=round(epoch/int(config["epochs"])*85, 2), training_curve=curve, phase="training")
        if val_loss < best_loss - 1e-7:
            best_loss=val_loss; best_state={key:value.detach().cpu().clone() for key,value in model.state_dict().items()}; remaining=int(config["patience"])
        else:
            remaining -= 1
            if remaining <= 0: break
    model.load_state_dict(best_state); model.eval(); path=artifact_dir/f"{kind}.pt"
    torch.save({"state_dict":best_state,"kind":kind,"mean":mean,"std":std,"config":config}, path)
    def predict(rows):
        x,_=tensors(rows)
        with torch.no_grad(): values=model(x.to(device)).cpu().numpy()*std+mean
        return values
    return path, {"mean":mean,"std":std,"best_validation_loss":best_loss,"device":str(device)}, curve, predict


def _evaluation_rows(experiment_id, metrics):
    rows=[]
    for split_name, detail in metrics.items():
        if not isinstance(detail, dict) or "overall" not in detail: continue
        for kind, groups in {"overall":{"all":detail["overall"]}, **detail["groups"]}.items():
            for value, data in groups.items():
                rows.append(EvaluationResult(experiment_id=experiment_id, split=split_name, group_type=kind, group_value=str(value), sample_count=data["sample_count"], mae=data["mae"], rmse=data["rmse"], bias=data["bias"], persistence_mae=data.get("persistence_mae"), improvement_pct=data.get("improvement_pct")))
    return rows


def _run(experiment_id, signal):
    started=time.perf_counter(); artifact_dir=settings.model_dir/experiment_id
    try:
        _save(experiment_id,status="preparing",phase="building_samples",started_at=datetime.now(UTC),progress=2)
        with SessionLocal() as db: row=db.get(TrainingExperiment,experiment_id); model_type=row.model_type; quality=row.quality_profile; config=row.config; name=row.name
        _seed(int(config["seed"])); samples=build_samples(quality); groups={name:[row for row in samples if row.split==name] for name in ("train","validation","test","supplemental_2025")}
        if min(len(groups["train"]),len(groups["validation"]),len(groups["test"]))==0: raise ValueError("严格分组后某个主集合无样本")
        stats=split_statistics(samples); version=dataset_version(quality); artifact_dir.mkdir(parents=True,exist_ok=False)
        _save(experiment_id,status="training",phase="training",split_statistics=stats,dataset_version=version,artifact_dir=str(artifact_dir),progress=8)
        if model_type=="persistence":
            path=artifact_dir/"persistence.json"; path.write_text(json.dumps({"rule":"prediction=current_wind"},ensure_ascii=False),encoding="utf-8")
            extra={}; curve=[]; predict=lambda rows: np.asarray([row.winds[-1] for row in rows])
        elif model_type=="ridge": path,extra,curve,predict=_train_ridge(groups["train"],groups["validation"],config,artifact_dir,signal)
        else: path,extra,curve,predict=_train_deep(model_type,groups["train"],groups["validation"],config,artifact_dir,signal,experiment_id)
        _check(signal); _save(experiment_id,status="evaluating",phase="evaluating",progress=90,training_curve=curve)
        metrics={split:evaluation_details(rows,predict(rows)) for split,rows in groups.items() if rows}
        metadata={"experiment_id":experiment_id,"name":name,"model_type":model_type,"quality_profile":quality,"dataset_version":version,"feature_names":FEATURE_NAMES if model_type=="ridge" else ["cma_wind_ms"],"config":config,"extra":extra,"created_at":datetime.now(UTC).isoformat(),"training_seconds":time.perf_counter()-started}
        metadata_path=artifact_dir/"metadata.json"; metadata_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        model_id=str(uuid4())
        with SessionLocal() as db:
            db.add(ModelArtifact(id=model_id,experiment_id=experiment_id,name=name,model_type=model_type,model_path=str(path),metadata_path=str(metadata_path),dataset_version=version,feature_names=metadata["feature_names"],metrics=metrics))
            db.add_all(_evaluation_rows(experiment_id,metrics)); row=db.get(TrainingExperiment,experiment_id); row.status="succeeded"; row.phase="succeeded"; row.progress=100; row.metrics=metrics; row.training_curve=curve; row.finished_at=datetime.now(UTC); row.device=extra.get("device","cpu"); db.commit()
    except InterruptedError as exc: _save(experiment_id,status="cancelled",phase="cancelled",finished_at=datetime.now(UTC),error_message=str(exc))
    except Exception as exc: _save(experiment_id,status="failed",phase="failed",finished_at=datetime.now(UTC),error_message=f"{type(exc).__name__}: {exc}")
    finally:
        with _lock: _signals.pop(experiment_id,None)


def list_experiments(model_type=None,status=None):
    with SessionLocal() as db:
        stmt=select(TrainingExperiment).order_by(TrainingExperiment.created_at.desc())
        if model_type: stmt=stmt.where(TrainingExperiment.model_type==model_type)
        if status: stmt=stmt.where(TrainingExperiment.status==status)
        results=[]
        for row in db.scalars(stmt):
            item=experiment_dict(row)
            item["metrics"]={split:{"overall":detail.get("overall")} for split,detail in (row.metrics or {}).items() if isinstance(detail,dict)}
            results.append(item)
        return results


def get_experiment(experiment_id):
    with SessionLocal() as db:
        row=db.get(TrainingExperiment,experiment_id)
        if not row: raise LookupError("实验不存在")
        result=experiment_dict(row); model=db.scalar(select(ModelArtifact).where(ModelArtifact.experiment_id==experiment_id))
        result["model"]={column.name:_utc(getattr(model,column.name)) for column in ModelArtifact.__table__.columns} if model else None
        return result


def list_models():
    with SessionLocal() as db:
        results=[]
        for row in db.scalars(select(ModelArtifact).order_by(ModelArtifact.created_at.desc())):
            item={column.name:_utc(getattr(row,column.name)) for column in ModelArtifact.__table__.columns}
            item["metrics"]={split:{"overall":detail.get("overall")} for split,detail in (row.metrics or {}).items() if isinstance(detail,dict)}
            results.append(item)
        return results


def delete_experiment(experiment_id, confirmed=False):
    if not confirmed: raise ValueError("删除实验需要二次确认")
    with SessionLocal() as db:
        row=db.get(TrainingExperiment,experiment_id)
        if not row: raise LookupError("实验不存在")
        if row.status in ACTIVE: raise ValueError("运行中实验不能删除")
        artifact=Path(row.artifact_dir).resolve() if row.artifact_dir else None
        root=settings.model_dir.resolve()
        db.execute(delete(PredictionRecord).where(PredictionRecord.model_id.in_(select(ModelArtifact.id).where(ModelArtifact.experiment_id==experiment_id))))
        db.execute(delete(EvaluationResult).where(EvaluationResult.experiment_id==experiment_id)); db.execute(delete(ModelArtifact).where(ModelArtifact.experiment_id==experiment_id)); db.delete(row); db.commit()
    if artifact and artifact.parent==root and artifact.exists(): shutil.rmtree(artifact)


def _load_predictor(model: ModelArtifact):
    metadata=json.loads(Path(model.metadata_path).read_text(encoding="utf-8")); kind=model.model_type
    if kind=="persistence": return metadata,lambda winds:float(winds[-1])
    if kind=="ridge":
        bundle=joblib.load(model.model_path)
        return metadata,lambda winds:float(bundle["model"].predict(bundle["scaler"].transform([list(winds)+[winds[-1]-winds[-2],winds[-1]-winds[-3]]]))[0])
    checkpoint=torch.load(model.model_path,map_location="cpu",weights_only=True); config=checkpoint["config"]
    network=RecurrentRegressor(kind,hidden_size=int(config["hidden_size"]),num_layers=int(config["num_layers"]),dropout=float(config["dropout"])); network.load_state_dict(checkpoint["state_dict"]); network.eval()
    def predict(winds):
        values=(np.asarray(winds,dtype=np.float32)-checkpoint["mean"])/checkpoint["std"]
        with torch.no_grad(): return float(network(torch.tensor(values).view(1,4,1)).item()*checkpoint["std"]+checkpoint["mean"])
    return metadata,predict


def historical_predict(model_id: str, typhoon_id: int, forecast_time: datetime) -> dict:
    with SessionLocal() as db:
        model=db.get(ModelArtifact,model_id); event=db.get(TyphoonEvent,typhoon_id)
        if not model or not event: raise LookupError("模型或台风事件不存在")
        if model.model_type=="safnet": raise ValueError("SAF-Net 必须使用完整 ERA5 时空样本推理接口")
        latest=select(TyphoonObservation).where(TyphoonObservation.typhoon_id==typhoon_id,TyphoonObservation.track_type=="MAIN").order_by(TyphoonObservation.observation_time,TyphoonObservation.id)
        by_time={row.observation_time:row for row in db.scalars(latest)}
        times=[forecast_time-timedelta(hours=value) for value in (18,12,6,0)]; rows=[by_time.get(moment) for moment in times]
        metadata,predictor=_load_predictor(model)
        allowed={"O","V"} if metadata["quality_profile"]=="strict" else {"O","V","I","P"}
        if any(row is None or row.cma_wind_ms is None or row.cma_iflag not in allowed for row in rows): raise ValueError("该起报时刻没有符合模型质量规则的连续四个6小时观测")
        winds=tuple(float(row.cma_wind_ms) for row in rows); predicted=predictor(winds); target_time=forecast_time+timedelta(hours=6); actual=by_time.get(target_time); actual_value=float(actual.cma_wind_ms) if actual and actual.cma_wind_ms is not None and actual.cma_iflag in allowed else None
        record=PredictionRecord(id=str(uuid4()),model_id=model_id,typhoon_id=typhoon_id,sid=event.sid,forecast_time=forecast_time,target_time=target_time,predicted_wind=predicted,actual_wind=actual_value,error=predicted-actual_value if actual_value is not None else None,input_features={"winds":winds,"times":[value.isoformat()+"Z" for value in times]},quality_profile=metadata["quality_profile"]); db.add(record); db.commit()
        return {"id":record.id,"sid":event.sid,"name":event.name,"forecast_time":forecast_time.isoformat()+"Z","target_time":target_time.isoformat()+"Z","predicted_wind":predicted,"actual_wind":actual_value,"error":record.error,"model_id":model_id,"model_name":model.name,"model_type":model.model_type,"model_created_at":_utc(model.created_at),"data_source":"NOAA IBTrACS v04r01 / CMA 2分钟风速","quality_profile":metadata["quality_profile"],"input_winds":winds,"historical_backtest":True}
