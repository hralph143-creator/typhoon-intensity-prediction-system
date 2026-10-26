from __future__ import annotations
import socket, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/Scripts/python.exe'
def port_available(port:int)->bool:
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:return sock.connect_ex(('127.0.0.1',port))!=0
def main()->int:
    if sys.argv[1:]==['--check']:
        from check_environment import main as check
        return check()
    if sys.argv[1:]:
        print(f"[错误] 不支持的参数：{' '.join(sys.argv[1:])}")
        print('可用命令：run.bat 或 run.bat --check')
        return 2
    for port,label in ((8000,'后端'),(5173,'前端')):
        if not port_available(port):
            print(f'[错误] {label}端口 {port} 已被占用，请先停止占用程序。')
            return 1
    if not (ROOT/'frontend/node_modules').is_dir():
        print('[错误] 前端依赖尚未安装，请在 frontend 目录运行 npm install。')
        return 1
    flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
    (ROOT/'logs').mkdir(exist_ok=True)
    with (ROOT/'logs/backend-console.log').open('a',encoding='utf-8') as backend_log, (ROOT/'logs/frontend-console.log').open('a',encoding='utf-8') as frontend_log:
        subprocess.Popen([str(PYTHON),'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8000'],cwd=ROOT,creationflags=flags,stdout=backend_log,stderr=subprocess.STDOUT)
        subprocess.Popen(['cmd.exe','/d','/c','npm.cmd','run','dev'],cwd=ROOT/'frontend',creationflags=flags,stdout=frontend_log,stderr=subprocess.STDOUT)
    print('[启动] 前后端服务启动命令已执行。')
    print('前端地址：http://127.0.0.1:5173')
    print('API 文档：http://127.0.0.1:8000/docs')
    return 0
if __name__=='__main__':raise SystemExit(main())
