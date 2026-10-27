"""Windows 启动入口：检查配置、启动缺失服务、确认就绪并保留日志。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_environment import backend_is_ours, configure_output, frontend_is_ours, port_available, version


def stop_created_process(process: subprocess.Popen) -> None:
    """仅回收本次启动、尚未完成启动的进程及其子进程。"""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    configure_output()
    if sys.argv[1:] == ["--check"]:
        from scripts.check_environment import main as check
        return check()
    if sys.argv[1:]:
        print(f"[错误] 不支持的参数：{' '.join(sys.argv[1:])}")
        print("可用命令：run.bat 或 run.bat --check")
        return 2
    try:
        from backend.app.core.config import settings
        from backend.app.db.database import init_db
    except Exception as exc:
        print(f"[错误] 后端依赖或配置有误：{exc}")
        print("请先运行 .venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt")
        return 1

    if not (3, 11) <= sys.version_info[:2] <= (3, 12):
        print("[错误] 请使用 Python 3.11 或 3.12。")
        return 1
    if not version(["node", "--version"]) or not version(["npm.cmd" if sys.platform == "win32" else "npm", "--version"]):
        print("[错误] 缺少 Node.js 或 npm，请安装 Node.js 22+ 后重试。")
        return 1
    if not (ROOT / "frontend/node_modules/.package-lock.json").is_file():
        print("[错误] 前端依赖尚未安装，请在 frontend 目录运行 npm ci。")
        return 1

    host = "127.0.0.1" if settings.app_host in ("0.0.0.0", "::") else settings.app_host
    backend_free = port_available(settings.app_port, host)
    frontend_free = port_available(5173)
    backend_ready = backend_is_ours(host, settings.app_port, settings.app_name, str(settings.database_path)) if not backend_free else False
    frontend_ready = frontend_is_ours() if not frontend_free else False
    for port, available, ready, label in (
        (settings.app_port, backend_free, backend_ready, "后端"),
        (5173, frontend_free, frontend_ready, "前端"),
    ):
        if not available and not ready:
            print(f"[错误] {label}端口 {port} 已被其他服务占用，或本项目服务尚未就绪。")
            return 1

    try:
        if not backend_ready:
            init_db()
    except Exception as exc:
        print(f"[错误] 数据库初始化或迁移失败：{exc}")
        return 1
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    runtime_env = os.environ.copy()
    runtime_env["PYTHONUTF8"] = "1"
    runtime_env["PYTHONIOENCODING"] = "utf-8"
    runtime_env["VITE_BACKEND_TARGET"] = f"http://{host}:{settings.app_port}"
    (ROOT / "logs").mkdir(exist_ok=True)
    created: list[subprocess.Popen] = []
    try:
        with (ROOT / "logs/backend-console.log").open("a", encoding="utf-8") as backend_log, (ROOT / "logs/frontend-console.log").open("a", encoding="utf-8") as frontend_log:
            if not backend_ready:
                created.append(subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", settings.app_host, "--port", str(settings.app_port)],
                    cwd=ROOT, env=runtime_env, creationflags=flags, stdout=backend_log, stderr=subprocess.STDOUT,
                ))
            if not frontend_ready:
                command = ["cmd.exe", "/d", "/c", "npm.cmd", "run", "dev"] if sys.platform == "win32" else ["npm", "run", "dev"]
                created.append(subprocess.Popen(command, cwd=ROOT / "frontend", env=runtime_env, creationflags=flags, stdout=frontend_log, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            backend_ready = backend_is_ours(host, settings.app_port, settings.app_name, str(settings.database_path))
            frontend_ready = frontend_is_ours()
            if backend_ready and frontend_ready:
                print("[成功] 后端、数据库和前端服务均已就绪。")
                print("前端地址：http://127.0.0.1:5173")
                print(f"API 文档：http://{host}:{settings.app_port}/docs")
                print("服务日志：logs/backend-console.log、logs/frontend-console.log")
                return 0
            if any(process.poll() is not None for process in created):
                raise RuntimeError("服务进程提前退出")
            time.sleep(0.25)
        raise TimeoutError("服务未在 35 秒内就绪")
    except (OSError, RuntimeError, TimeoutError) as exc:
        for process in reversed(created):
            stop_created_process(process)
        print(f"[错误] {exc}。已停止本次未完成启动的服务。")
        print("请查看 logs/backend-console.log、logs/frontend-console.log，并运行 run.bat --check。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
