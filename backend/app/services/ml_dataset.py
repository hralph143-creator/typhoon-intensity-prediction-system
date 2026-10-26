"""可重复的台风强度样本构建；仅使用起报时刻及之前信息。"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Iterable
from types import SimpleNamespace

from sqlalchemy import func, select

from backend.app.db.database import SessionLocal
from backend.app.models.typhoon import SourceFile, TyphoonEvent, TyphoonObservation

STRICT_FLAGS = {"O", "V"}
EXTENDED_FLAGS = {"O", "V", "I", "P"}
SPLIT_YEARS = {"train": range(2014, 2022), "validation": range(2022, 2024), "test": range(2024, 2025), "supplemental_2025": range(2025, 2026)}
FEATURE_NAMES = ["wind_t-18h", "wind_t-12h", "wind_t-6h", "wind_t", "delta_6h", "delta_12h"]


@dataclass(frozen=True)
class IntensitySample:
    sid: str
    typhoon_id: int
    season: int
    forecast_time: datetime
    target_time: datetime
    winds: tuple[float, float, float, float]
    target: float
    quality: str
    split: str

    @property
    def ridge_features(self) -> list[float]:
        values = list(self.winds)
        return values + [values[-1] - values[-2], values[-1] - values[-3]]

    def serializable(self) -> dict:
        result = asdict(self)
        result["winds"] = list(self.winds)
        result["forecast_time"] = self.forecast_time.isoformat() + "Z"
        result["target_time"] = self.target_time.isoformat() + "Z"
        result["wind_unit"] = "m/s"
        return result


def _split(season: int) -> str | None:
    return next((name for name, years in SPLIT_YEARS.items() if season in years), None)


def _accepted(flag: str | None, profile: str) -> bool:
    return flag in (STRICT_FLAGS if profile == "strict" else EXTENDED_FLAGS)


def latest_main_observations(db=None):
    own = db is None
    db = db or SessionLocal()
    latest = select(func.max(TyphoonObservation.id)).where(TyphoonObservation.track_type == "MAIN").group_by(TyphoonObservation.typhoon_id, TyphoonObservation.observation_time)
    stmt = select(
        TyphoonObservation.id, TyphoonObservation.typhoon_id, TyphoonObservation.observation_time,
        TyphoonObservation.cma_wind, TyphoonObservation.cma_wind_ms, TyphoonObservation.cma_iflag,
        TyphoonEvent.sid, TyphoonEvent.season,
    ).join(TyphoonEvent, TyphoonEvent.id == TyphoonObservation.typhoon_id).where(TyphoonObservation.id.in_(latest)).order_by(TyphoonObservation.typhoon_id, TyphoonObservation.observation_time)
    rows = [(SimpleNamespace(id=row.id, typhoon_id=row.typhoon_id, observation_time=row.observation_time, cma_wind=row.cma_wind, cma_wind_ms=row.cma_wind_ms, cma_iflag=row.cma_iflag), SimpleNamespace(id=row.typhoon_id, sid=row.sid, season=row.season)) for row in db.execute(stmt)]
    if own:
        db.close()
    return rows


def build_samples(profile: str = "strict", db=None) -> list[IntensitySample]:
    if profile not in {"strict", "extended"}:
        raise ValueError("质量配置必须为 strict 或 extended")
    grouped: dict[int, list[tuple[TyphoonObservation, TyphoonEvent]]] = defaultdict(list)
    for observation, event in latest_main_observations(db):
        grouped[event.id].append((observation, event))
    samples: list[IntensitySample] = []
    offsets = [timedelta(hours=value) for value in (18, 12, 6, 0, -6)]
    for rows in grouped.values():
        by_time = {observation.observation_time: (observation, event) for observation, event in rows}
        for forecast_time, (_, event) in by_time.items():
            times = [forecast_time - offset for offset in offsets]
            selected = [by_time.get(moment) for moment in times]
            if any(item is None for item in selected):
                continue
            observations = [item[0] for item in selected if item]
            if any(item.cma_wind_ms is None or not _accepted(item.cma_iflag, profile) for item in observations):
                continue
            split = _split(event.season)
            if not split:
                continue
            winds = tuple(float(item.cma_wind_ms) for item in observations[:4])
            samples.append(IntensitySample(event.sid, event.id, event.season, forecast_time, times[-1], winds, float(observations[-1].cma_wind_ms), profile, split))
    return samples


def dataset_version(profile: str, db=None) -> str:
    own = db is None
    db = db or SessionLocal()
    hashes = list(db.scalars(select(SourceFile.sha256).order_by(SourceFile.id)))
    if own:
        db.close()
    digest = sha256(("|".join(hashes) + f"|6h-four-step-{profile}-v1").encode()).hexdigest()[:16]
    return f"ibtracs-v04r01-{profile}-{digest}"


def split_statistics(samples: Iterable[IntensitySample]) -> dict:
    grouped: dict[str, list[IntensitySample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.split].append(sample)
    result = {}
    sid_sets = {}
    for split in SPLIT_YEARS:
        rows = grouped[split]
        sids = {row.sid for row in rows}
        sid_sets[split] = sids
        targets = [row.target for row in rows]
        result[split] = {
            "sample_count": len(rows), "event_count": len(sids),
            "years": sorted({row.season for row in rows}),
            "wind_min": min(targets) if targets else None, "wind_max": max(targets) if targets else None,
            "wind_mean": sum(targets) / len(targets) if targets else None,
        }
    intersections = {f"{left}_{right}": sorted(sid_sets[left] & sid_sets[right]) for index, left in enumerate(sid_sets) for right in list(sid_sets)[index + 1:]}
    result["sid_intersections"] = intersections
    result["no_sid_leakage"] = all(not values for values in intersections.values())
    return result


def audit_data() -> dict:
    with SessionLocal() as db:
        all_rows = [(SimpleNamespace(track_type=row.track_type,cma_wind=row.cma_wind,cma_wind_ms=row.cma_wind_ms,cma_iflag=row.cma_iflag,iflag=row.iflag,quality_flags=row.quality_flags or []),SimpleNamespace(season=row.season)) for row in db.execute(select(TyphoonObservation.track_type,TyphoonObservation.cma_wind,TyphoonObservation.cma_wind_ms,TyphoonObservation.cma_iflag,TyphoonObservation.iflag,TyphoonObservation.quality_flags,TyphoonEvent.season).join(TyphoonEvent))]
        main_rows = latest_main_observations(db)
        strict = build_samples("strict", db)
        extended = build_samples("extended", db)
        yearly_events = {year: count for year, count in db.execute(select(TyphoonEvent.season, func.count()).group_by(TyphoonEvent.season)).all()}
    yearly_valid = Counter(event.season for observation, event in main_rows if observation.cma_wind_ms is not None)
    track_types = Counter(observation.track_type for observation, _ in all_rows)
    flags = Counter((observation.cma_iflag or "_") for observation, _ in all_rows)
    iflags = Counter((observation.iflag or "") for observation, _ in all_rows)
    intervals = Counter()
    lengths = Counter()
    by_sid = defaultdict(list)
    for observation, event in main_rows:
        by_sid[event.sid].append(observation.observation_time)
    for times in by_sid.values():
        lengths[len(times)] += 1
        intervals.update(int((right - left).total_seconds() / 3600) for left, right in zip(times, times[1:]))
    def window_counts(profile):
        allowed = STRICT_FLAGS if profile == "strict" else EXTENDED_FLAGS
        histories = labels = 0; yearly = Counter()
        grouped = defaultdict(list)
        for observation, event in main_rows: grouped[event.sid].append((observation, event))
        for rows in grouped.values():
            by_time = {observation.observation_time: (observation, event) for observation, event in rows}
            for moment, (_, event) in by_time.items():
                inputs = [by_time.get(moment - timedelta(hours=hours)) for hours in (18,12,6,0)]
                if any(item is None or item[0].cma_wind_ms is None or item[0].cma_iflag not in allowed for item in inputs): continue
                histories += 1; target = by_time.get(moment + timedelta(hours=6))
                if target and target[0].cma_wind_ms is not None and target[0].cma_iflag in allowed:
                    labels += 1; yearly[event.season] += 1
        return {"complete_history_windows":histories,"future_6h_labels":labels,"yearly_final_samples":dict(sorted(yearly.items()))}
    valid = sum(1 for observation, _ in all_rows if observation.cma_wind_ms is not None)
    special = sum(1 for observation, _ in all_rows if observation.cma_wind == 17 or "special_cma_wind" in observation.quality_flags)
    abnormal = sum(1 for observation, _ in all_rows if observation.cma_wind_ms is not None and not 0 < observation.cma_wind_ms <= 100)
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "yearly_event_count": yearly_events,
        "yearly_valid_cma_wind": dict(sorted(yearly_valid.items())), "track_type_count": dict(track_types),
        "cma_iflag_count": dict(flags), "iflag_top": dict(iflags.most_common(30)),
        "sequence_length_distribution": dict(sorted(lengths.items())), "interval_hours": dict(sorted(intervals.items())),
        "event_sequence_lengths": {sid: len(times) for sid, times in sorted(by_sid.items())},
        "observation_count": len(all_rows), "valid_cma_wind_count": valid,
        "missing_cma_wind_count": len(all_rows) - valid, "missing_cma_wind_ratio": (len(all_rows) - valid) / len(all_rows),
        "special_cma_17_count": special, "abnormal_wind_count": abnormal,
        "strict_samples": split_statistics(strict), "extended_samples": split_statistics(extended),
        "strict_sample_count": len(strict), "extended_sample_count": len(extended),
        "strict_window_audit": window_counts("strict"), "extended_window_audit": window_counts("extended"),
        "rules": {"strict": "MAIN且CMA IFLAG第3位为O/V，连续t-18h至t+6h", "extended": "MAIN且CMA IFLAG第3位为O/V/I/P，同样严格6小时连续"},
    }
