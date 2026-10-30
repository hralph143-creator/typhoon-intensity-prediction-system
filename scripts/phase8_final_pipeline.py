"""Bounded Phase 8 final expansion and three-seed SAF-Net training runner."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.app.services.era5_service import create_scale_batch,get_public_batch
from backend.app.services.phase8_service import data_quality_audit,freeze_dataset
from backend.app.services.safnet_training import create_experiment
from backend.app.services.ml_training import get_experiment


def emit(value):print(json.dumps(value,ensure_ascii=False,default=str),flush=True)


def expand(max_batches:int,batch_size:int)->None:
    for number in range(1,max_batches+1):
        audit=data_quality_audit();emit({"phase":"audit","batch_number":number,"samples":audit["samples"],"events":audit["events"],"splits":audit["splits"],"remaining":audit["remaining"],"formal":audit["formal_training_allowed"]})
        if audit["formal_training_allowed"]:return
        batch=create_scale_batch(batch_size);batch_id=batch["id"];emit({"phase":"batch_created","batch_number":number,"id":batch_id,"requested":batch["requested"],"source":batch["source_id"],"plan":[[x["split"],x["sid"],x["forecast_time"],x.get("cached_time_count")] for x in batch["plan"]]})
        deadline=time.time()+2100
        while time.time()<deadline:
            time.sleep(5);batch=get_public_batch(batch_id)
            if batch["status"] not in {"queued","running"}:break
            if batch["cursor"] and batch["cursor"]%3==0:emit({"phase":"batch_progress","id":batch_id,"cursor":batch["cursor"],"requested":batch["requested"],"completed":batch["completed"],"failed":batch["failed"],"cache_hits":batch["cache_hits"],"seconds":batch["duration_seconds"]})
        emit({"phase":"batch_finished","id":batch_id,"status":batch["status"],"cursor":batch["cursor"],"completed":batch["completed"],"failed":batch["failed"],"cache_hits":batch["cache_hits"],"actual_bytes":batch["actual_bytes"],"seconds":batch["duration_seconds"],"errors":batch["errors"]})
        if batch["status"]!="succeeded":raise SystemExit("batch did not succeed; expansion stopped safely")
    audit=data_quality_audit();emit({"phase":"expansion_limit","samples":audit["samples"],"events":audit["events"],"splits":audit["splits"],"remaining":audit["remaining"],"formal":audit["formal_training_allowed"]})


def train(seeds:list[int])->None:
    audit=data_quality_audit()
    if not audit["formal_training_allowed"]:raise SystemExit("formal training gate is not satisfied")
    manifest=freeze_dataset();emit({"phase":"dataset_frozen","dataset_version":manifest["dataset_version"],"manifest_sha256":manifest["manifest_sha256"]})
    for seed in seeds:
        experiment=create_experiment({"name":f"SAF-Net 第八阶段正式实验 seed={seed}","config":{"epochs":50,"batch_size":16,"learning_rate":.001,"patience":8,"gradient_clip":1.0,"seed":seed}});experiment_id=experiment["id"];emit({"phase":"training_created","seed":seed,"id":experiment_id})
        deadline=time.time()+3600
        while time.time()<deadline:
            time.sleep(5);experiment=get_experiment(experiment_id)
            if experiment["status"] not in {"queued","preparing","training","evaluating"}:break
            emit({"phase":"training_progress","seed":seed,"status":experiment["status"],"epoch":experiment["current_epoch"],"progress":experiment["progress"]})
        emit({"phase":"training_finished","seed":seed,"id":experiment_id,"status":experiment["status"],"epoch":experiment["current_epoch"],"metrics":experiment["metrics"],"error":experiment["error_message"]})
        if experiment["status"]!="succeeded":raise SystemExit("training failed; remaining seeds were not started")


parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest="command",required=True)
expand_parser=sub.add_parser("expand");expand_parser.add_argument("--max-batches",type=int,default=1);expand_parser.add_argument("--batch-size",type=int,default=12)
train_parser=sub.add_parser("train");train_parser.add_argument("--seeds",nargs="+",type=int,default=[42,2028,3407])
args=parser.parse_args()
if args.command=="expand":expand(args.max_batches,args.batch_size)
else:train(args.seeds)
