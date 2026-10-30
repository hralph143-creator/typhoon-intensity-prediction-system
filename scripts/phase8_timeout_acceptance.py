"""Manual live acceptance: a cloud reader exceeding its budget is really terminated."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import settings
from backend.app.services.era5_sources import run_read_worker
from backend.app.services.era5_service import _sample_remote_request
from backend.app.services.ml_dataset import build_samples

sample = build_samples("strict")[0]
request = _sample_remote_request(sample)
target = settings.era5_raw_dir / "timeout-acceptance.nc"
started = time.perf_counter()
try:
    run_read_worker("google_arco", request, target, 1)
    raise SystemExit("FAIL: reader unexpectedly completed inside one second")
except TimeoutError as exc:
    partial = target.with_suffix(".partial.nc")
    print({
        "status": "passed",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "message": str(exc),
        "target_exists": target.exists(),
        "partial_exists": partial.exists(),
    })
finally:
    target.unlink(missing_ok=True)
    target.with_suffix(".partial.nc").unlink(missing_ok=True)
