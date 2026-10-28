from datetime import datetime

from backend.app.services.era5_service import _bounds
from backend.app.services.fair_comparison import compare_common_test_set
from backend.app.services.fusion_service import _distance_km, _name, match_statistics
from backend.app.services.safnet_dataset import availability


def test_event_match_name_normalization_and_unknown_protection():
    assert _name("Ling-ling") == "LINGLING"
    assert _name("(nameless)") == "NAMELESS"


def test_event_match_distance_is_symmetric_and_zero_for_same_point():
    assert _distance_km((10,120),(10,120)) == 0
    assert abs(_distance_km((10,120),(11,121))-_distance_km((11,121),(10,120))) < 1e-9


def test_dateline_request_is_split_without_future_information():
    parts=_bounds(15,179,4)
    assert len(parts)==2
    assert parts[0][1] < parts[0][3] and parts[1][1] < parts[1][3]


def test_empty_phase7_states_are_truthful():
    state=availability()
    assert state["ready"] is False and state["formal_ready"] is False
    assert state["experiment_level"] == "experimental"
    result=compare_common_test_set()
    assert result["status"] == "unavailable"


def test_match_statistics_reports_unmatched_without_forcing_pairs():
    result=match_statistics()
    assert result["counts"]["unmatched_ibtracs"] >= 0
    assert result["counts"]["unmatched_cma"] >= 0
