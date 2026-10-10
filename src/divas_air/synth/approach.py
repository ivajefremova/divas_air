"""Semi-synthetic approach scenes: anomalies injected into real `fco` hours (specs/02 item 12).

One UTC hour of non-held-out traffic is one scene; a track belongs to the hour in
which it starts, whole. No behavioral anomalies on approach.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point

from divas_air import config, params
from divas_air.geo import to_metric, to_wgs84
from divas_air.synth.inject import add_labels
from divas_air.synth.motion import not_held_out
from divas_air.synth.scene import SOURCE, finalize, run_events

APPROACH_CAUSES = (
    "degraded",
    "technical_error",
    "gnss_anomaly",
    "possible_spoofing",
    "possible_interference",
)
APPROACH_WEIGHTS = (0.2, 0.25, 0.2, 0.25, 0.1)
MIN_TRACKS = 15  # an hour needs this many tracks to become a scene
SECTOR_RADIUS_M = (2000.0, 6000.0)


def eligible_points() -> pd.DataFrame:
    """`fco` points minus the last REAL_HOLDOUT_DAYS days."""
    p = pd.read_parquet(config.PROCESSED / "points" / "fco.parquet")
    return p[not_held_out(p["t"])].reset_index(drop=True)


def _plan(points: pd.DataFrame, cause: str, rng, used: set) -> dict | None:
    span = points.groupby("track_id")["t"].agg(["min", "max", "size"])
    span = span[(span["max"] - span["min"] > 150) & ~span.index.isin(list(used))]
    if span.empty:
        return None
    if cause == "possible_interference":
        dur = rng.uniform(60, 180)
        for _ in range(12):
            tid = span.index[int(rng.integers(len(span)))]
            lo, hi = span.loc[tid, "min"], span.loc[tid, "max"]
            onset = rng.uniform(lo, max(hi - dur, lo + 1))
            mid = points[(points["t"] >= onset) & (points["t"] < onset + dur)]
            g = mid[mid["track_id"] == tid]
            if g.empty:
                continue
            cx, cy = to_metric(
                g["lon"].iloc[[len(g) // 2]], g["lat"].iloc[[len(g) // 2]]
            )
            r = rng.uniform(*SECTOR_RADIUS_M)
            x, y = to_metric(mid["lon"], mid["lat"])
            if mid.loc[np.hypot(x - cx[0], y - cy[0]) < r, "track_id"].nunique() >= 3:
                ring = np.asarray(Point(cx[0], cy[0]).buffer(r, 32).exterior.coords)
                lon, lat = to_wgs84(ring[:, 0], ring[:, 1])
                region = shapely.Polygon(np.column_stack([lon, lat]))
                return {
                    "cause": cause,
                    "onset_t": onset,
                    "duration_s": dur,
                    "region": region,
                    "params": {"radius_m": r},
                }
        return None
    tid = span.index[int(rng.integers(len(span)))]
    lo, hi = span.loc[tid, "min"], span.loc[tid, "max"]
    dur = min(
        rng.uniform(40, 120) if cause == "technical_error" else rng.uniform(60, 200),
        hi - lo - 10,
    )
    return {
        "cause": cause,
        "onset_t": rng.uniform(lo + 5, hi - dur),
        "duration_s": dur,
        "track_ids": [tid],
        "params": {},
    }


def approach_scenes(n_hours: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng([params.SEED, seed, 1])
    pts = eligible_points()
    start = pts.groupby("track_id")["t"].transform("min")
    pts["_hour"] = (start // 3600).astype("int64")
    counts = pts.groupby("_hour")["track_id"].nunique()
    hours = np.sort(counts[counts >= MIN_TRACKS].index.to_numpy())
    chosen = np.sort(rng.choice(hours, size=min(n_hours, len(hours)), replace=False))

    frames, events = [], []
    for h in chosen:
        g = pts[pts["_hour"] == h].drop(columns="_hour").copy()
        scene_id = "approach_" + pd.Timestamp(
            int(h) * 3600, unit="s", tz="UTC"
        ).strftime("%Y%m%d%H")
        g["base_track_id"] = g["track_id"]
        g["scene_id"] = scene_id
        rest = g["track_id"].str.split(":", n=1).str[1]  # "<asset>:<segment>"
        g["track_id"] = SOURCE + ":" + rest.str.replace(r":(\d+)$", r":a\1", regex=True)
        g["source"] = SOURCE
        g = add_labels(g)
        plans, used = [], set()
        for _ in range(int(rng.integers(5, 12))):
            cause = str(rng.choice(APPROACH_CAUSES, p=APPROACH_WEIGHTS))
            plan = _plan(g, cause, rng, used)
            if plan is not None:
                plans.append(plan)
                used.update(plan.get("track_ids") or [])
        g, ev = run_events(g, plans, scene_id=scene_id, seed=int(h), layers=None)
        frames.append(g)
        events.append(ev)
    return finalize(pd.concat(frames, ignore_index=True)), pd.concat(
        events, ignore_index=True
    )
