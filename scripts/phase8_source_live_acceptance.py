"""Manual live acceptance: prove pause/resume and finish one balanced public batch."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.services.era5_service import (
    cancel_public_batch,
    create_public_batch,
    get_public_batch,
    resume_public_batch,
)


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


batch = create_public_batch(1)
batch_id = batch["id"]
emit({"created": batch_id, "plan": [(item["split"], item["sid"]) for item in batch["plan"]]})
time.sleep(2)
cancel_public_batch(batch_id)
time.sleep(2)
paused = get_public_batch(batch_id)
emit({"paused": paused["status"], "cursor": paused["cursor"], "completed": paused["completed"], "failed": paused["failed"]})
resume_public_batch(batch_id)
deadline = time.time() + 240
result = get_public_batch(batch_id)
while result["status"] in {"queued", "running"} and time.time() < deadline:
    time.sleep(2)
    result = get_public_batch(batch_id)
emit({
    "final": result["status"],
    "cursor": result["cursor"],
    "completed": result["completed"],
    "failed": result["failed"],
    "actual_bytes": result["actual_bytes"],
    "metrics": result["metrics"],
})
