"""使用内存 HTTP 传输验证下载恢复，不访问网络或业务数据目录。"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services import ibtracs_download as downloader


URL = "https://example.test/ibtracs.WP.list.v04r01.csv"
CSV = (
    b"SID,SEASON,ISO_TIME,LAT,LON,BASIN,TRACK_TYPE\n"
    b" ,year, ,degrees_north,degrees_east, , \n"
    b"2014001N10001,2014,2014-01-01 00:00:00,10,130,WP,MAIN\n"
)


def seed_partial(tmp_path, body=CSV, offset=80):
    (tmp_path / "official-download.csv.part").write_bytes(body[:offset])
    (tmp_path / "official-download.part.json").write_text(
        json.dumps({"url": URL, "etag": '"same-file"'}), encoding="utf-8"
    )
    return offset


def test_resumes_matching_range_without_duplicated_bytes(tmp_path):
    offset = seed_partial(tmp_path)

    def respond(request):
        assert request.headers["range"] == f"bytes={offset}-"
        assert request.headers["if-range"] == '"same-file"'
        return httpx.Response(
            206,
            content=CSV[offset:],
            headers={"content-range": f"bytes {offset}-{len(CSV)-1}/{len(CSV)}", "etag": '"same-file"'},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = downloader.download_csv(tmp_path, url=URL, client=client, retries=0)
    assert result["file_size"] == len(CSV)
    assert (tmp_path / result["path"]).read_bytes() == CSV
    assert not (tmp_path / "official-download.csv.part").exists()


def test_server_ignoring_range_restarts_instead_of_appending(tmp_path):
    seed_partial(tmp_path)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=CSV)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = downloader.download_csv(tmp_path, url=URL, client=client, retries=0)
    assert requests[0].headers.get("range")
    assert (tmp_path / result["path"]).read_bytes() == CSV


def test_rejects_incorrect_range_start(tmp_path):
    seed_partial(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        206, content=CSV, headers={"content-range": f"bytes 0-{len(CSV)-1}/{len(CSV)}"}
    ))) as client:
        with pytest.raises(ValueError, match="不匹配的 Range"):
            downloader.download_csv(tmp_path, url=URL, client=client, retries=0)
    assert not (tmp_path / "official-download.json").exists()


def test_changed_etag_discards_stale_partial_before_retry(tmp_path, monkeypatch):
    seed_partial(tmp_path)
    calls = []
    cancel = threading.Event()
    monkeypatch.setattr(cancel, "wait", lambda _: False)

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            offset = 80
            return httpx.Response(206, content=CSV[offset:], headers={
                "content-range": f"bytes {offset}-{len(CSV)-1}/{len(CSV)}", "etag": '"changed"',
            })
        assert "range" not in request.headers
        return httpx.Response(200, content=CSV)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = downloader.download_csv(tmp_path, url=URL, client=client, retries=1, cancel=cancel)
    assert len(calls) == 2
    assert (tmp_path / result["path"]).read_bytes() == CSV


def test_timeout_is_retried_and_success_is_archived(tmp_path, monkeypatch):
    calls = []
    progress = []
    cancel = threading.Event()
    monkeypatch.setattr(cancel, "wait", lambda _: False)

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("test timeout", request=request)
        return httpx.Response(200, content=CSV)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = downloader.download_csv(tmp_path, url=URL, client=client, retries=1, cancel=cancel, progress=progress.append)
    assert len(calls) == 2
    assert any(item["phase"] == "retrying" for item in progress)
    assert result["file_size"] == len(CSV)


def test_timeout_retry_limit_is_enforced(tmp_path, monkeypatch):
    calls = []
    cancel = threading.Event()
    monkeypatch.setattr(cancel, "wait", lambda _: False)

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("test timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.ReadTimeout):
            downloader.download_csv(tmp_path, url=URL, client=client, retries=2, cancel=cancel)
    assert len(calls) == 3
    assert not (tmp_path / "official-download.json").exists()


def test_unknown_total_reports_bytes_without_invented_percentage(tmp_path):
    updates = []
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(CSV)))) as client:
        result = downloader.download_csv(tmp_path, url=URL, client=client, retries=0, progress=updates.append)
    downloading = [update for update in updates if update["phase"] == "downloading"]
    assert downloading
    assert all(update["total_bytes"] is None and update["progress"] is None for update in downloading)
    assert downloading[-1]["downloaded_bytes"] == len(CSV)
    assert result["file_size"] == len(CSV)


def test_cancel_keeps_partial_and_never_creates_final_archive(tmp_path):
    body = CSV + b"\n" * (600 * 1024)
    cancel = threading.Event()

    def progress(update):
        if update["phase"] == "downloading":
            cancel.set()

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body, headers={"etag": '"same-file"'}))) as client:
        with pytest.raises(downloader.DownloadCancelled):
            downloader.download_csv(tmp_path, url=URL, client=client, retries=0, cancel=cancel, progress=progress)
    partial = tmp_path / "official-download.csv.part"
    assert 0 < partial.stat().st_size < len(body)
    assert (tmp_path / "official-download.part.json").exists()
    assert not (tmp_path / "official-download.json").exists()


def test_html_error_content_is_not_archived_as_csv(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"<html>not a dataset</html>\n"))) as client:
        with pytest.raises(ValueError, match="IBTrACS CSV"):
            downloader.download_csv(tmp_path, url=URL, client=client, retries=0)
    assert not list(tmp_path.glob("*_ibtracs*.csv"))
    assert not (tmp_path / "official-download.json").exists()


def test_insufficient_disk_space_fails_before_body_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=CSV))) as client:
        with pytest.raises(ValueError, match="磁盘剩余空间不足"):
            downloader.download_csv(tmp_path, url=URL, client=client, retries=0)
    assert not (tmp_path / "official-download.csv.part").exists()


def test_valid_cached_file_is_reused_without_network(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=CSV))) as client:
        first = downloader.download_csv(tmp_path, url=URL, client=client, retries=0)

    def must_not_connect(_):
        pytest.fail("valid cached file should not trigger another HTTP request")

    with httpx.Client(transport=httpx.MockTransport(must_not_connect)) as client:
        cached = downloader.download_csv(tmp_path, url=URL, client=client, retries=0)
    assert cached["cached"] is True
    assert cached["sha256"] == first["sha256"]
