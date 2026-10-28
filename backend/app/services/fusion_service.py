"""IBTrACS 与独立 CMA 最佳路径事件的可审计关联。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import delete, func, select

from backend.app.db.database import SessionLocal
from backend.app.models.typhoon import CrossSourceEventMatch, TyphoonEvent, TyphoonObservation

VERSION = "event-match-v1"
UNKNOWN_NAMES = {"", "UNNAMED", "NAMELESS", "(NAMELESS)", "NOT NAMED", "INVEST"}


def _name(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2-lat1, lon2-lon1
    h = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 12742 * asin(sqrt(min(1.0, h)))


def _track(db, event_id: int) -> dict[datetime, tuple[float, float]]:
    rows = db.scalars(select(TyphoonObservation).where(
        TyphoonObservation.typhoon_id == event_id,
        TyphoonObservation.track_type == "MAIN",
    ).order_by(TyphoonObservation.observation_time, TyphoonObservation.id))
    result = {}
    for row in rows:
        result.setdefault(row.observation_time, (row.cma_lat or row.latitude, row.cma_lon or row.longitude))
    return result


def recompute_matches() -> dict:
    """仅用同年、时间重叠、名称和同 UTC 轨迹距离计算，名称永不单独定案。"""
    with SessionLocal() as db:
        ib = list(db.scalars(select(TyphoonEvent).where(TyphoonEvent.source == "ibtracs")))
        cma = list(db.scalars(select(TyphoonEvent).where(TyphoonEvent.source == "cma")))
        by_year = defaultdict(list)
        for event in cma: by_year[event.season].append(event)
        tracks = {}
        candidates = []
        for left in ib:
            for right in by_year[left.season]:
                start=max(left.first_observation,right.first_observation); end=min(left.last_observation,right.last_observation)
                if end < start: continue
                overlap_h=(end-start).total_seconds()/3600
                shorter=max(1.0,min((left.last_observation-left.first_observation).total_seconds()/3600,(right.last_observation-right.first_observation).total_seconds()/3600))
                overlap_ratio=min(1.0,overlap_h/shorter)
                if overlap_ratio < .2: continue
                lt=tracks.setdefault(left.id,_track(db,left.id)); rt=tracks.setdefault(right.id,_track(db,right.id))
                common=sorted(set(lt)&set(rt)); distances=[_distance_km(lt[t],rt[t]) for t in common]
                mean_distance=sum(distances)/len(distances) if distances else None
                same_name=_name(left.name)==_name(right.name) and _name(left.name) not in UNKNOWN_NAMES
                number_hint=(right.number is not None and str(right.number).zfill(2) in (right.sid or "")[-4:])
                spatial=max(0.0,1-mean_distance/500) if mean_distance is not None else 0.0
                confidence=.45*overlap_ratio+.40*spatial+.15*float(same_name)
                if len(common)<2 or mean_distance is None or mean_distance>500: continue
                status="confirmed" if confidence>=.78 and mean_distance<=200 and (same_name or len(common)>=4) else "candidate"
                candidates.append({"left":left,"right":right,"confidence":confidence,"status":status,"basis":{"same_name":same_name,"number_hint":number_hint,"overlap_hours":round(overlap_h,1),"overlap_ratio":round(overlap_ratio,4),"common_times":len(common),"mean_track_distance_km":round(mean_distance,2),"max_track_distance_km":round(max(distances),2)}})
        left_counts=defaultdict(int); right_counts=defaultdict(int)
        for item in candidates:
            if item["status"]=="confirmed": left_counts[item["left"].id]+=1; right_counts[item["right"].id]+=1
        db.execute(delete(CrossSourceEventMatch).where(CrossSourceEventMatch.algorithm_version==VERSION))
        for item in candidates:
            conflict=left_counts[item["left"].id]>1 or right_counts[item["right"].id]>1
            db.add(CrossSourceEventMatch(ibtracs_event_id=item["left"].id,cma_event_id=item["right"].id,ibtracs_sid=item["left"].sid,cma_sid=item["right"].sid,status="conflict" if conflict else item["status"],confidence=round(item["confidence"],6),basis=item["basis"],conflict=conflict,algorithm_version=VERSION))
        db.commit()
    return match_statistics()


def match_statistics(limit: int = 100) -> dict:
    with SessionLocal() as db:
        rows=list(db.scalars(select(CrossSourceEventMatch).where(CrossSourceEventMatch.algorithm_version==VERSION).order_by(CrossSourceEventMatch.confidence.desc())))
        counts={key:sum(x.status==key for x in rows) for key in ("confirmed","candidate","conflict")}
        total_ib=db.scalar(select(func.count()).select_from(TyphoonEvent).where(TyphoonEvent.source=="ibtracs")) or 0
        total_cma=db.scalar(select(func.count()).select_from(TyphoonEvent).where(TyphoonEvent.source=="cma")) or 0
        matched_ib={x.ibtracs_event_id for x in rows if x.status=="confirmed"}; matched_cma={x.cma_event_id for x in rows if x.status=="confirmed"}
        return {"algorithm_version":VERSION,"counts":{**counts,"unmatched_ibtracs":total_ib-len(matched_ib),"unmatched_cma":total_cma-len(matched_cma)},"items":[{"id":x.id,"ibtracs_sid":x.ibtracs_sid,"cma_sid":x.cma_sid,"status":x.status,"confidence":x.confidence,"basis":x.basis,"conflict":x.conflict} for x in rows[:limit]]}
