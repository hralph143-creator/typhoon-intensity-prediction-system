"""执行第十阶段真实消融与多时效概率实验。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.app.db.database import init_db
from backend.app.services.phase10_service import run_phase10_experiments


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--force",action="store_true");parser.add_argument("--epochs",type=int,default=30);args=parser.parse_args();init_db();result=run_phase10_experiments(args.force,max(1,min(args.epochs,200)));print(json.dumps({"dataset_version":result["dataset_version"],"runs":len(result["runs"]),"selected_candidate":result["selected_candidate"]},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
