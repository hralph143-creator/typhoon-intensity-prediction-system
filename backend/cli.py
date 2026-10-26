"""命令行下载/导入与 API 复用同一任务、校验和数据库流程。"""
import argparse
import json
import sys
from pathlib import Path

from backend.app.db.database import init_db
from backend.app.services.ibtracs_jobs import recover_interrupted_jobs, start_job, wait_for_job


def main() -> int:
    parser = argparse.ArgumentParser(description="云浪智析 IBTrACS 真实数据管理")
    subcommands = parser.add_subparsers(dest="command", required=True)
    download = subcommands.add_parser("download", help="下载官方 WP CSV 并导入研究时段；默认复用校验通过的缓存")
    download.add_argument("--force", action="store_true", help="重新获取官方文件")
    local = subcommands.add_parser("import", help="从本地真实 CSV 导入，保留原文件和校验信息")
    local.add_argument("path", type=Path)
    args = parser.parse_args()
    init_db()
    recover_interrupted_jobs()
    if args.command == "download":
        job = start_job("download", filename="ibtracs.WP.list.v04r01.csv", force=args.force)
    else:
        if not args.path.is_file():
            parser.error("找不到指定的 CSV 文件")
        job = start_job("import", path=args.path, filename=args.path.name)
    print(f"任务已创建：{job['id']}", flush=True)
    result = wait_for_job(job["id"], timeout=3600)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
