"""流式下载、条件断点续传和原始文件原子归档。"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import httpx

from backend.app.core.config import settings


class DownloadCancelled(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_csv(path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        columns = [value.strip() for value in next(reader, [])]
        if not {"SID", "SEASON", "ISO_TIME", "LAT", "LON", "BASIN"}.issubset(columns):
            raise ValueError("文件不是有效的 IBTrACS CSV：缺少必要字段")
        second = next(reader, None)
        if not second:
            raise ValueError("CSV 没有数据记录")
        is_units = second[columns.index("SEASON")].strip().lower() == "year" if len(second) == len(columns) else False
        if is_units and not next(reader, None):
            raise ValueError("CSV 没有数据记录")


def download_csv(
    directory: Path | None = None,
    *,
    url: str | None = None,
    force: bool = False,
    cancel: threading.Event | None = None,
    progress: Callable[[dict], None] | None = None,
    client: httpx.Client | None = None,
    retries: int | None = None,
) -> dict:
    directory = directory or settings.raw_data_dir
    directory.mkdir(parents=True, exist_ok=True)
    url = url or settings.ibtracs_url
    cancel = cancel or threading.Event()
    report = progress or (lambda _: None)
    manifest = directory / "official-download.json"
    partial = directory / "official-download.csv.part"
    partial_meta = directory / "official-download.part.json"
    if not force and manifest.exists():
        try:
            cached = json.loads(manifest.read_text(encoding="utf-8"))
            path = directory / Path(cached["path"]).name
            if cached.get("url") == url and path.exists() and sha256_file(path) == cached["sha256"]:
                validate_csv(path)
                return {**cached, "path": str(path), "cached": True}
        except (OSError, ValueError, KeyError):
            pass
    owned_client = client is None
    client = client or httpx.Client(timeout=settings.download_timeout, follow_redirects=True)
    max_retries = retries if retries is not None else settings.download_retries
    try:
        for attempt in range(max_retries + 1):
            if cancel.is_set():
                raise DownloadCancelled("下载已取消，临时文件保留供下次恢复")
            offset = partial.stat().st_size if partial.exists() else 0
            saved = {}
            if partial_meta.exists():
                try:
                    saved = json.loads(partial_meta.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            if saved.get("url") != url or not (saved.get("etag") or saved.get("last_modified")):
                offset = 0
            headers = {"Accept-Encoding": "identity", "User-Agent": "YunlangResearch/0.2 (IBTrACS historical analysis)"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
                headers["If-Range"] = saved.get("etag") or saved["last_modified"]
            try:
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code == 416 and offset:
                        partial.unlink(missing_ok=True)
                        partial_meta.unlink(missing_ok=True)
                        raise httpx.RequestError("服务器无法恢复此断点，将从头重试")
                    response.raise_for_status()
                    total = None
                    if response.status_code == 206:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
                        if not match or int(match[1]) != offset:
                            raise ValueError("服务器返回了不匹配的 Range，拒绝拼接文件")
                        total = int(match[3])
                        expected_end = int(match[2]) + 1
                        if expected_end != total:
                            raise ValueError("服务器未提供所请求的完整剩余字节")
                        validator = response.headers.get("etag") or response.headers.get("last-modified")
                        previous = saved.get("etag") or saved.get("last_modified")
                        if offset and validator and validator != previous:
                            partial.unlink(missing_ok=True)
                            partial_meta.unlink(missing_ok=True)
                            raise httpx.RequestError("服务器文件已变化，将重新开始下载")
                    else:
                        offset = 0  # 不支持 Range：正确退回完整重下
                        size = response.headers.get("content-length")
                        total = int(size) if size and size.isdigit() else None
                    if total and total > settings.upload_max_bytes:
                        raise ValueError("下载文件超过配置的最大文件大小")
                    if shutil.disk_usage(directory).free < ((total or 128 * 1024 * 1024) - offset) + 64 * 1024 * 1024:
                        raise ValueError("磁盘剩余空间不足，需预留文件大小及 64 MiB")
                    metadata = {"url": url, "etag": response.headers.get("etag"), "last_modified": response.headers.get("last-modified")}
                    partial_meta.write_text(json.dumps(metadata), encoding="utf-8")
                    started, last_report, downloaded = time.monotonic(), 0.0, offset
                    with partial.open("ab" if offset else "wb") as handle:
                        for chunk in response.iter_bytes(256 * 1024):
                            if cancel.is_set():
                                raise DownloadCancelled("下载已取消，临时文件保留供下次恢复")
                            downloaded += len(chunk)
                            if downloaded > settings.upload_max_bytes:
                                raise ValueError("下载内容超过最大文件大小")
                            handle.write(chunk)
                            now = time.monotonic()
                            if now - last_report >= 0.3:
                                report({"downloaded_bytes": downloaded, "total_bytes": total, "speed_bps": (downloaded - offset) / max(now - started, 0.001), "progress": round(downloaded / total * 100, 1) if total else None, "phase": "downloading"})
                                last_report = now
                    if total is not None and downloaded != total:
                        raise httpx.RequestError("下载字节数与服务器声明不一致，保留断点以重试")
                    validate_csv(partial)
                    digest = sha256_file(partial)
                    final = directory / f"{digest[:16]}_ibtracs.WP.list.v04r01.csv"
                    if final.exists():
                        if sha256_file(final) != digest:
                            raise ValueError("归档目标文件校验失败")
                        partial.unlink()
                    else:
                        partial.replace(final)
                    result = {"path": str(final), "filename": "ibtracs.WP.list.v04r01.csv", "sha256": digest, "file_size": downloaded, **metadata, "cached": False}
                    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    partial_meta.unlink(missing_ok=True)
                    report({"downloaded_bytes": downloaded, "total_bytes": total, "speed_bps": 0.0, "progress": 100.0, "phase": "downloaded"})
                    return result
            except (httpx.HTTPError, OSError) as exc:
                report({"phase": "retrying", "error_message": f"第 {attempt + 1} 次下载失败：{exc}"})
                if attempt == max_retries:
                    raise
                if cancel.wait(min(2 ** attempt, 8)):
                    raise DownloadCancelled("下载已取消")
    finally:
        if owned_client:
            client.close()
    raise RuntimeError("下载未完成")
