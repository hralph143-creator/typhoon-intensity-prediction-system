from fastapi import APIRouter, Query

from backend.app.services.fusion_service import match_statistics, recompute_matches

router=APIRouter(prefix="/fusion",tags=["多源数据融合"])

def ok(data,message="请求成功"):return {"success":True,"message":message,"data":data}

@router.get("/matches")
def matches(limit:int=Query(100,ge=1,le=1000)):return ok(match_statistics(limit))

@router.post("/matches/recompute")
def recompute():return ok(recompute_matches(),"跨源事件关联已重新计算")
