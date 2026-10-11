"""Offline replay bundle (specs/06_api.md requirements 9-13).

    python -m divas_air.api.replay [--source demo]

Steps a fresh engine over the scripted demo scene and writes
data/processed/demo/replay/manifest.json and frames.jsonl: one frame per
REPLAY_STEP_S with the verdicts and the live and forecast risk zones. Static
halos never change, so frames leave them out (4.2 MB each); the map reads them
from map/layers/halos_static.geojson or GET /risk-zones.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from divas_air import config, contract, params
from divas_air.engine import TrustEngine, grid_ceil

REPLAY_DIR = config.PROCESSED / "demo" / "replay"
EVENTS = {  # event_id -> (kind, operator-facing title)
    "ev_phantom": (
        "phantom_incursion",
        "Phantom runway incursion: a tractor's position jumps onto the runway",
    ),
    "ev_real": (
        "real_incursion",
        "Real runway incursion: a fuel truck drives onto the runway",
    ),
    "ev_sector": ("sector_interference", "Sector GNSS interference on the apron"),
}


def manifest_events(events: pd.DataFrame) -> list[contract.ReplayEvent]:
    out = []
    for r in events.sort_values("t_onset").itertuples(index=False):
        kind, title = EVENTS[r.event_id]
        out.append(
            contract.ReplayEvent(
                event_id=r.event_id,
                kind=kind,
                title=title,
                t_start=float(r.t_onset),
                t_end=float(r.t_end),
                track_ids=[str(x) for x in r.track_ids],
            )
        )
    return out


def build(
    source: str = "demo", out_dir: Path = REPLAY_DIR, engine: TrustEngine | None = None
) -> Path:
    points = pd.read_parquet(config.PROCESSED / "points" / f"{source}.parquet")
    events = pd.read_parquet(config.PROCESSED / "synth" / f"{source}_events.parquet")
    eng = engine if engine is not None else TrustEngine.from_disk()
    step = float(params.REPLAY_STEP_S)
    t = points["t"].to_numpy(dtype="float64")
    grid = np.arange(grid_ceil(t.min()), grid_ceil(t.max()) + 1e-6, step)

    out_dir.mkdir(parents=True, exist_ok=True)
    frames_path = out_dir / "frames.jsonl"
    prev = -np.inf
    with open(frames_path, "w") as fh:
        for now in grid:
            eng.ingest(points[(t > prev) & (t <= now)])
            prev = now
            verdicts = eng.step(float(now))
            frame = contract.ReplayFrame(
                t=float(now),
                verdicts=verdicts,
                risk_zones=eng.risk_zones(float(now), static=False),
            )
            fh.write(frame.model_dump_json(exclude_none=True) + "\n")

    manifest = contract.ReplayManifest(
        airport="LIRF",
        t_start=float(grid[0]),
        t_end=float(grid[-1]),
        step_s=params.REPLAY_STEP_S,
        n_frames=len(grid),
        frames_file=frames_path.name,
        events=manifest_events(events),
    )
    (out_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    return out_dir


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m divas_air.api.replay")
    ap.add_argument("--source", default="demo")
    a = ap.parse_args(argv)
    t0 = time.time()
    out = build(a.source)
    m = contract.ReplayManifest.model_validate_json((out / "manifest.json").read_text())
    print(
        f"{m.n_frames} frames, {len(m.events)} events, {time.time() - t0:.0f} s -> {out}"
    )


if __name__ == "__main__":
    main()
