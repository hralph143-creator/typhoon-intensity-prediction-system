"""启动器必须识别本项目服务，不能接管无关的端口占用。"""
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
