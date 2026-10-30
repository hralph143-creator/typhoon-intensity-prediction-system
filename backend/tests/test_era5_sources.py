import json
import subprocess

import pytest

from backend.app.services import era5_sources


def request():
    return {
        "times": ["2024-08-01T00:00:00Z", "2024-08-01T06:00:00Z"],
        "area": [25.0, 120.0, 17.0, 128.0],
    }


def test_approved_source_registry_is_explicit():
    assert set(era5_sources.ADAPTERS) == {"aws_icechunk", "google_arco", "ecmwf_arco"}
    assert era5_sources.SOURCE_IDS[0] == "auto"


def test_source_estimates_are_metadata_based_and_not_claimed_actual():
    google = era5_sources.ADAPTERS["google_arco"].estimate(request())
    aws = era5_sources.ADAPTERS["aws_icechunk"].estimate(request())
    assert google["estimated_chunks"] == 4
    assert google["estimated_uncompressed_bytes"] == 4 * 721 * 1440 * 4
    assert aws["estimated_chunks"] > 0
    assert google["actual_transfer_bytes"] is None
    assert aws["actual_transfer_bytes"] is None


def test_auto_selection_uses_fastest_successful_quality_benchmark(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "default": "auto",
        "benchmarks": {
            "aws_icechunk": {"status": "succeeded", "cold_read_seconds": 49.0},
            "google_arco": {"status": "succeeded", "cold_read_seconds": 13.0},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(era5_sources, "STATE_PATH", state)
    assert era5_sources.choose_source({}) == "google_arco"


def test_ecmwf_probe_reports_missing_authorization(monkeypatch):
    from backend.app.services import era5_service
    monkeypatch.setattr(era5_service, "credential_status", lambda: {"configured": False})
    result = era5_sources.ADAPTERS["ecmwf_arco"].probe()
    assert result["status"] == "unauthorized"
    assert result["variables"] == {"u10": None, "v10": None}


def test_stop_process_escalates_to_kill():
    class Process:
        killed = False
        terminated = False
        waits = 0
        def poll(self): return None
        def terminate(self): self.terminated = True
        def kill(self): self.killed = True
        def wait(self, _timeout):
            self.waits += 1
            if self.waits == 1: raise subprocess.TimeoutExpired("reader", 5)
            return -9
    process = Process()
    era5_sources._stop_process(process)
    assert process.terminated and process.killed


def test_rejects_unapproved_reader(tmp_path):
    with pytest.raises(ValueError, match="不支持匿名读取"):
        era5_sources.run_read_worker("ecmwf_arco", request(), tmp_path / "x.nc", 1)


def test_pause_event_is_not_a_data_failure():
    from backend.app.services.era5_service import _data_batch_errors, _operational_batch_event
    assert _operational_batch_event({"error": "用户暂停批次"})
    assert not _operational_batch_event({"error": "ValueError: missing variable"})
    assert _data_batch_errors([{"error":"用户暂停批次"},{"build":{"built":3}},{"error":"ValueError: bad"}]) == [{"error":"ValueError: bad"}]


def test_adapter_cache_key_separates_source_and_version():
    from backend.app.services.era5_service import _adapter_cache_key
    base={"source_id":"google_arco","dataset_version":"v1","sid":"A","times":["t"],"centers":[[1,2]],"area":[2,1,0,3],"variables":["u10","v10"],"processing_version":"v2","crop_version":"crop-v2","accessed_at":"ignored"}
    assert "accessed_at" not in _adapter_cache_key(base)
    assert _adapter_cache_key(base) != _adapter_cache_key({**base,"source_id":"aws_icechunk"})
    assert _adapter_cache_key(base) != _adapter_cache_key({**base,"dataset_version":"v2"})
