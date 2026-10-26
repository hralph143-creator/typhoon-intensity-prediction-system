from __future__ import annotations
import importlib.util, socket, sqlite3, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def port_available(port:int)->bool:
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:return sock.connect_ex(('127.0.0.1',port))!=0
def version(command:list[str])->str|None:
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=10,check=True)
        return (result.stdout or result.stderr).strip()
    except (OSError,subprocess.SubprocessError):return None
def main()->int:
    checks:list[tuple[str,bool,str]]=[]
    checks.append(('Python 3.12',sys.version_info[:2]==(3,12),sys.version.split()[0]))
    checks.append(('虚拟环境',sys.prefix!=sys.base_prefix,sys.prefix))
    for name in ('fastapi','uvicorn','sqlalchemy','pydantic'):checks.append((f'Python 依赖 {name}',importlib.util.find_spec(name) is not None,'已安装'))
    node,npm=version(['node','--version']),version(['npm.cmd' if sys.platform=='win32' else 'npm','--version'])
    checks.extend([('Node.js',node is not None,node or '未找到'),('npm',npm is not None,npm or '未找到'),('前端依赖',(ROOT/'frontend/node_modules').is_dir(),'frontend/node_modules')])
    for directory in ('backend','frontend','data/raw','data/processed','data/cache','logs'):checks.append((f'目录 {directory}',(ROOT/directory).is_dir(),str(ROOT/directory)))
    database=ROOT/'data/system.db';database_ok=False
    if database.exists():
        try:
            with sqlite3.connect(database) as connection:connection.execute('SELECT 1')
            database_ok=True
        except sqlite3.Error:pass
    checks.append(('SQLite 数据库',database_ok,str(database)))
    for port in (8000,5173):
        available=port_available(port);checks.append((f'端口 {port}',available,'可用' if available else '已占用'))
    print('\n云浪智析 · 环境健康检查\n'+'='*62)
    for label,passed,detail in checks:print(f"[{'通过' if passed else '失败'}] {label}: {detail}")
    print('='*62);failed=[label for label,passed,_ in checks if not passed]
    if failed:print('检查未通过：'+'、'.join(failed));return 1
    print('全部检查通过。');return 0
if __name__=='__main__':raise SystemExit(main())
