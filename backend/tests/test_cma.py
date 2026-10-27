from backend.app.services.cma_service import inspect_file, parse_cma_file


def test_cma_parser_preserves_direct_units_and_missing_wind(tmp_path):
    path = tmp_path / "CH2025BST.txt"
    path.write_text(
        "66666 2501    2 0001 2501 0 3 WUTIP                              20260304\n"
        "2025061012 1 154 1143  998      15\n"
        "2025061015 0 155 1142 1000       9\n",
        encoding="utf-8",
    )
    events = list(parse_cma_file(path))
    assert len(events) == 1
    assert events[0]["sid"] == "CMA-2025-0001"
    assert events[0]["observations"][0]["wind_ms"] == 15.0
    assert events[0]["observations"][1]["wind_ms"] is None
    assert "cma_wind_below_10" in events[0]["observations"][1]["quality_flags"]
    assert "cma_three_hour_landfall_record" in events[0]["observations"][1]["quality_flags"]
    assert inspect_file(path)["observation_count"] == 2
