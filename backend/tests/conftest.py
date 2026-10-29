"""测试全局数据库隔离：任何测试都不写入业务 system.db。"""
import os
from pathlib import Path
from uuid import uuid4

import pytest

_test_root = Path(__file__).resolve().parents[2] / ".tmp" / f"pytest-{uuid4().hex}"
_test_root.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + (_test_root / "isolated.db").as_posix()


@pytest.fixture(scope="session", autouse=True)
def initialized_isolated_database():
    from backend.app.db.database import init_db
    init_db()


@pytest.fixture(autouse=True)
def isolated_source_status(monkeypatch, tmp_path):
    # 第一阶段的空目录状态测试仍需要真实空目录，而不是读取正式CSV归档。
    from backend.app.services import data_source_service
    monkeypatch.setattr(data_source_service, "PROJECT_ROOT", tmp_path)
