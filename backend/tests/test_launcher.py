"""启动器必须识别本项目服务，不能接管无关的端口占用。"""
from pathlib import Path

from scripts import check_environment


def test_backend_identity_requires_matching_database(monkeypatch):
    def fake_fetch(url):
        if url.endswith("/api/health"):
            return {"data": {"status": "healthy"}}
        return {"data": {"software_name": "云浪测试", "database_path": "D:/other.db"}}

    monkeypatch.setattr(check_environment, "fetch_json", fake_fetch)
    assert not check_environment.backend_is_ours("127.0.0.1", 8000, "云浪测试", "D:/current.db")
    assert check_environment.backend_is_ours("127.0.0.1", 8000, "云浪测试", "D:/other.db")


def test_backend_identity_requires_healthy_service(monkeypatch):
    def fake_fetch(url):
        if url.endswith("/api/health"):
            return {"data": {"status": "unhealthy"}}
        return {"data": {"software_name": "云浪测试", "database_path": "D:/current.db"}}

    monkeypatch.setattr(check_environment, "fetch_json", fake_fetch)
    assert not check_environment.backend_is_ours("127.0.0.1", 8000, "云浪测试", "D:/current.db")


def test_unrelated_frontend_is_not_reused(monkeypatch):
    monkeypatch.setattr(check_environment, "fetch_json", lambda _: {"name": "another-application"})
    assert not check_environment.frontend_is_ours()


def test_local_frontend_is_recognized(monkeypatch):
    monkeypatch.setattr(check_environment, "fetch_json", lambda _: {"name": "typhoon-prediction-frontend"})
    assert check_environment.frontend_is_ours()


def test_run_bat_is_windows_safe_and_opens_application():
    content=(Path(__file__).resolve().parents[2]/"run.bat").read_bytes()
    assert content.startswith(b"\xef\xbb\xbf@echo off\r\n")
    assert content.count(b"\n")==content.count(b"\r\n")
    text=content.decode("utf-8-sig")
    assert 'set /p FRONTEND_URL=<"logs\\frontend-url.txt"' in text
    assert 'start "" "%FRONTEND_URL%"' in text
    assert '"%~1"=="--no-browser"' in text
    assert "CLOUDWAVE_NO_PAUSE" in text
