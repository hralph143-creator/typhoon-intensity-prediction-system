"""Create reproducible Phase-8 final acceptance artifacts from persisted real runs."""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.config import PROJECT_ROOT
from backend.app.db.database import SessionLocal
from backend.app.models.era5 import SpatiotemporalSample
from backend.app.models.ml import ModelArtifact, TrainingExperiment
from backend.app.services.fair_comparison import compare_common_test_set
from backend.app.services.phase8_service import data_quality_audit, freeze_dataset
from backend.app.services.report_service import create_report, get_report
from backend.app.services.safnet_training import _sample_tensors, load_model


def main() -> None:
    output = PROJECT_ROOT / "data" / "exports" / "phase8-final"
    output.mkdir(parents=True, exist_ok=True)
    audit = data_quality_audit()
    if not audit["formal_training_allowed"]:
        raise RuntimeError(f"formal gate failed: {audit['problems']} / {audit['remaining']}")
    manifest = freeze_dataset()

    with SessionLocal() as db:
        experiments = list(db.scalars(select(TrainingExperiment).where(
            TrainingExperiment.model_type == "safnet",
            TrainingExperiment.status == "succeeded",
            TrainingExperiment.dataset_version == manifest["dataset_version"],
        ).order_by(TrainingExperiment.created_at)))
        artifacts = {x.experiment_id: x for x in db.scalars(select(ModelArtifact).where(ModelArtifact.model_type == "safnet"))}
        if len(experiments) < 3:
            raise RuntimeError("fewer than three successful formal SAF-Net seeds")
        seed_runs = []
        for experiment in experiments:
            curve = experiment.training_curve or []
            best = min(curve, key=lambda row: row["validation_loss"])
            artifact = artifacts[experiment.id]
            metadata_path = Path(artifact.metadata_path)
            metadata = json.loads(metadata_path.read_text("utf-8"))
            metadata.update(best_epoch=best["epoch"], best_validation_loss=best["validation_loss"])
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            seed_runs.append({
                "seed": experiment.seed, "experiment_id": experiment.id, "model_id": artifact.id,
                "epochs_ran": experiment.current_epoch, "best_epoch": best["epoch"],
                "best_validation_loss": best["validation_loss"],
                "validation_mae": experiment.metrics["validation"]["overall"]["mae"],
                "test_mae": experiment.metrics["test"]["overall"]["mae"],
                "test_rmse": experiment.metrics["test"]["overall"]["rmse"],
                "test_bias": experiment.metrics["test"]["overall"]["bias"],
                "sha256": metadata["sha256"], "training_seconds": metadata["training_seconds"],
            })
        selected = min(seed_runs, key=lambda row: row["validation_mae"])
        artifact = db.get(ModelArtifact, selected["model_id"])
        sample = db.scalar(select(SpatiotemporalSample).where(SpatiotemporalSample.split == "test", SpatiotemporalSample.processing_version == "spatiotemporal-v2").order_by(SpatiotemporalSample.forecast_time))
        model, normalization, metadata = load_model(artifact)
        wind, temporal = _sample_tensors(sample, normalization)
        with torch.no_grad():
            first, attention = model(wind, temporal, return_attention=True)
            second = model(wind, temporal)
        first_value = float(first.item() * normalization.target_std + normalization.target_mean)
        second_value = float(second.item() * normalization.target_std + normalization.target_mean)

    comparison = compare_common_test_set()
    summary = {
        "dataset": {key: manifest[key] for key in ("dataset_version", "manifest_sha256", "samples", "events", "splits", "years", "intensity_bands")},
        "seed_runs": seed_runs,
        "selection": {**selected, "criterion": "minimum_validation_mae", "test_set_used_for_selection": False},
        "reload_consistency": {"sample_id": sample.id, "first": first_value, "second": second_value, "absolute_difference": abs(first_value-second_value), "passed": abs(first_value-second_value) < 1e-9},
        "common_test": comparison,
        "limitations": ["测试集仅 6 个独立事件，且相邻窗口集中于少数事件。", "结果是历史再分析回测，不是实时业务预报。", "注意力权重不表示气象因果关系。"],
    }
    (output / "acceptance-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "seed-runs.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(seed_runs[0])); writer.writeheader(); writer.writerows(seed_runs)
    with (output / "common-test.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["model_type", "model_id", "sample_count", "mae", "rmse", "bias", "persistence_mae", "improvement_pct", "inference_seconds"]); writer.writeheader(); writer.writerows(comparison["items"])

    attention_data = {"sample_id": sample.id, "model_id": selected["model_id"], "spatial": attention["spatial"].squeeze(0).squeeze(1).tolist(), "temporal": attention["temporal"].squeeze(0).tolist(), "note": "Network attention is descriptive, not causal."}
    (output / "attention.json").write_text(json.dumps(attention_data, ensure_ascii=False), encoding="utf-8")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].imshow(attention["spatial"][0, -1, 0].numpy(), cmap="viridis"); axes[0].set_title("Spatial attention at t")
    axes[1].imshow(attention["temporal"][0, 0, 0].numpy(), cmap="magma", vmin=0, vmax=1); axes[1].set_title("Temporal attention, head 1")
    for axis in axes: axis.set_xlabel("Attention is not causality")
    fig.tight_layout(); fig.savefig(output / "attention.png", dpi=180); plt.close(fig)

    reports = []
    for payload in (
        {"report_type": "model", "experiment_id": selected["experiment_id"], "title": "SAF-Net 正式训练与测试报告", "force": True},
        {"report_type": "comprehensive", "title": "第八阶段最终科研实验验收报告", "force": True},
    ):
        report = create_report(payload)
        while report["report_status"] in {"queued", "generating"}:
            time.sleep(.5); report = get_report(report["id"])
        if report["report_status"] != "succeeded": raise RuntimeError(f"report failed: {report}")
        reports.append(report)
    (output / "reports.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "selection": summary["selection"], "reload": summary["reload_consistency"], "reports": [x["id"] for x in reports]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
