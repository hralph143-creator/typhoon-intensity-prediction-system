"""只读环境检查；复用应用配置，不下载数据、不修改业务数据库。"""
from __future__ import annotations

import importlib.util
import json
import socket
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def fetch_json(url: str) -> dict | None:
    try:
        # Local health probes must not depend on the user's HTTP proxy settings.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=1) as response:
            payload = json.load(response)
            return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def backend_is_ours(host: str, port: int, name: str, database_path: str) -> bool:
    info = fetch_json(f"http://{host}:{port}/api/system/info")
    health = fetch_json(f"http://{host}:{port}/api/health")
    if not info or not health:
        return False
    data = info.get("data", {})
    health_data = health.get("data", {})
    if not isinstance(data, dict) or not isinstance(health_data, dict):
        return False
    return (
        data.get("software_name") == name
        and data.get("database_path") == database_path
        and health_data.get("status") == "healthy"
    )


def frontend_is_ours() -> bool:
    package = fetch_json("http://127.0.0.1:5173/package.json")
    return bool(package and package.get("name") == "typhoon-prediction-frontend")


def version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        return (result.stdout or result.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    configure_output()
    checks: list[tuple[str, bool, str]] = [
        ("Python 3.12", sys.version_info[:2] == (3, 12), sys.version.split()[0]),
        ("虚拟环境", sys.prefix != sys.base_prefix, sys.prefix),
    ]
    for name in ("fastapi", "uvicorn", "sqlalchemy", "pydantic", "pydantic_settings", "httpx", "multipart", "numpy", "sklearn", "joblib", "openpyxl", "torch", "cdsapi", "xarray", "netCDF4", "h5netcdf", "h5py"):
        installed = importlib.util.find_spec(name) is not None
        checks.append((f"Python 依赖 {name}", installed, "已安装" if installed else "未安装"))
    try:
        from backend.app.core.config import settings
    except Exception as exc:
        print(f"[失败] 应用配置无法读取：{exc}")
        print("请检查 .env 格式并安装 backend/requirements.txt 中的依赖。")
        return 1

    node = version(["node", "--version"])
    npm = version(["npm.cmd" if sys.platform == "win32" else "npm", "--version"])
    node_major = int(node.removeprefix("v").split(".")[0]) if node else 0
    checks.extend([
        ("Node.js 22+", node_major >= 22, node or "未找到"),
        ("npm", npm is not None, npm or "未找到"),
        ("前端依赖", (ROOT / "frontend/node_modules/.package-lock.json").is_file(), "frontend/node_modules"),
        ("示例配置", (ROOT / ".env.example").is_file(), ".env.example"),
    ])
    for directory in ("backend", "frontend", "data/raw", "data/processed", "data/cache", "logs", "checkpoints", "experiments"):
        checks.append((f"目录 {directory}", (ROOT / directory).is_dir(), str(ROOT / directory)))

    database = settings.database_path
    database_ok = False
    if database and database.exists():
        try:
            with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
                database_ok = connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        except sqlite3.Error:
            pass
    checks.append(("SQLite 数据库", database_ok, str(database or "当前仅支持本地 SQLite")))

    probe_host = "127.0.0.1" if settings.app_host in ("0.0.0.0", "::") else settings.app_host
    backend_free = port_available(settings.app_port, probe_host)
    backend_running = backend_is_ours(probe_host, settings.app_port, settings.app_name, str(database)) if not backend_free else False
    checks.append((f"后端端口 {settings.app_port}", backend_free or backend_running, "可用" if backend_free else "本项目服务正常运行" if backend_running else "被其他服务占用或本项目未就绪"))
    frontend_free = port_available(5173)
    frontend_running = frontend_is_ours() if not frontend_free else False
    checks.append(("前端端口 5173", frontend_free or frontend_running, "可用" if frontend_free else "本项目服务正常运行" if frontend_running else "被其他服务占用"))

    print("\n云浪智析 · 环境健康检查\n" + "=" * 62)
    for label, passed, detail in checks:
        print(f"[{'通过' if passed else '失败'}] {label}: {detail}")
    failed = [label for label, passed, _ in checks if not passed]
    print("=" * 62)
    print("检查未通过：" + "、".join(failed) if failed else "全部检查通过。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
