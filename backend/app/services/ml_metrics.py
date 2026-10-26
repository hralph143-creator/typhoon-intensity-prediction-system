from __future__ import annotations

import math
from collections import defaultdict

import numpy as np


def regression_metrics(actual, predicted, persistence=None) -> dict:
    actual = np.asarray(actual, dtype=float); predicted = np.asarray(predicted, dtype=float)
    errors = predicted - actual
    mae = float(np.mean(np.abs(errors)))
    result = {"sample_count": int(len(actual)), "mae": mae, "rmse": float(np.sqrt(np.mean(errors ** 2))), "bias": float(np.mean(errors))}
    if persistence is not None:
        p_mae = float(np.mean(np.abs(np.asarray(persistence, dtype=float) - actual)))
        result["persistence_mae"] = p_mae
        result["improvement_pct"] = None if p_mae == 0 else (p_mae - mae) / p_mae * 100
    return result


def evaluation_details(samples, predicted) -> dict:
    actual = [row.target for row in samples]; persistence = [row.winds[-1] for row in samples]
    overall = regression_metrics(actual, predicted, persistence)
    groups = {"year": defaultdict(list), "intensity": defaultdict(list), "sid": defaultdict(list)}
    def level(value):
        return "<17.2" if value < 17.2 else "17.2-24.4" if value < 24.5 else "24.5-32.6" if value < 32.7 else "32.7-41.4" if value < 41.5 else "41.5-50.9" if value < 51 else ">=51.0"
    for index, row in enumerate(samples):
        for kind, key in (("year", str(row.season)), ("intensity", level(row.target)), ("sid", row.sid)):
            groups[kind][key].append(index)
    grouped = {}
    for kind, values in groups.items():
        grouped[kind] = {key: regression_metrics([actual[i] for i in ids], [predicted[i] for i in ids], [persistence[i] for i in ids]) for key, ids in values.items()}
    points = [{"sid": row.sid, "season": row.season, "forecast_time": row.forecast_time.isoformat() + "Z", "target_time": row.target_time.isoformat() + "Z", "actual": row.target, "predicted": float(predicted[i]), "persistence": row.winds[-1], "error": float(predicted[i] - row.target)} for i, row in enumerate(samples)]
    extremes = sorted(points, key=lambda row: abs(row["error"]), reverse=True)[:20]
    return {"overall": overall, "groups": grouped, "points": points, "extreme_errors": extremes}
