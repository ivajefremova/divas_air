"""CLI: python -m divas_air.synth --seed 42 [--scenes 200] [--approach-hours 40]."""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from divas_air import config, schema
from divas_air.geo import MapLayers
from divas_air.synth.approach import approach_scenes
from divas_air.synth.scene import finalize, generate_scene

POINTS = config.PROCESSED / "points" / "synthetic.parquet"
EVENTS = config.PROCESSED / "synth" / "events.parquet"


def summary(points: pd.DataFrame, events: pd.DataFrame) -> str:
    lines = [
        f"scenes {points['scene_id'].nunique()}, tracks {points['track_id'].nunique()}, points {len(points)}"
    ]
    by = points.groupby("label_cause").agg(
        points=("t", "size"), tracks=("track_id", "nunique")
    )
    by["share"] = by["points"] / len(points)
    lines.append(by.to_string())
    lines.append(events.groupby("cause").size().rename("events").to_string())
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m divas_air.synth")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scenes", type=int, default=200)
    ap.add_argument("--approach-hours", type=int, default=40)
    a = ap.parse_args(argv)

    t = time.time()
    layers = MapLayers.load()
    rng = np.random.default_rng([a.seed, 7])
    pts, evs = [], []
    for i in range(a.scenes):
        n_assets = int(rng.integers(15, 41))
        n_aircraft = int(rng.integers(2, 7))
        p, e = generate_scene(
            a.seed * 1000 + i,
            n_vehicles=n_assets - n_aircraft,
            n_aircraft=n_aircraft,
            layers=layers,
        )
        pts.append(p)
        evs.append(e)
    print(f"ground scenes: {a.scenes} in {time.time() - t:.0f} s")
    if a.approach_hours > 0:
        p, e = approach_scenes(a.approach_hours, a.seed)
        pts.append(p)
        evs.append(e)
        print(f"approach scenes: {p['scene_id'].nunique()} in {time.time() - t:.0f} s")

    points = finalize(pd.concat(pts, ignore_index=True))
    schema.validate(points, labeled=True)
    events = pd.concat([e for e in evs if len(e)], ignore_index=True)
    POINTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    points.to_parquet(POINTS, index=False)
    events.to_parquet(EVENTS, index=False)
    print(summary(points, events))
    print(
        f"wrote {POINTS.relative_to(config.ROOT)} and {EVENTS.relative_to(config.ROOT)}"
    )


if __name__ == "__main__":
    main()
