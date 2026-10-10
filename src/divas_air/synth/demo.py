"""The scripted demo scene (specs/02_generator.md section 5).

python -m divas_air.synth.demo

Three events in order, with clean gaps: `ev_phantom` (a baggage tractor's
position jumps onto a runway), `ev_real` (a fuel truck really drives onto a
runway), `ev_sector` (interference over an apron cell with five parked vehicles).
"""

from __future__ import annotations

import json

import h3
import numpy as np
import pandas as pd
import shapely
from pyproj import Geod
from shapely.geometry import Point

from divas_air import config, params
from divas_air.geo import MapLayers
from divas_air.synth.motion import envelopes
from divas_air.synth.scene import _anchors, build_assets, finalize, nets, run_events

POINTS = config.PROCESSED / "points" / "demo.parquet"
EVENTS = config.PROCESSED / "synth" / "demo_events.parquet"
DEMO_SEED = params.SEED
DURATION_S = 600.0
N_VEHICLES, N_AIRCRAFT = 25, 6
T0 = params.SYNTH_T0 + 199_999 * params.SYNTH_SLOT_S  # a slot no ground scene uses
SCENE_ID = "demo_000"
PHANTOM = (65.0, 60.0)  # onset after scene start, duration
TRUCK_START = 210.0  # the truck leaves the road; labels start when it enters the runway
TRUCK_ON_RUNWAY_S = 60.0
SECTOR = (420.0, 150.0)
SECTOR_RADIUS_M = 150.0
N_PARKED = 5


def _runway_points(layers):
    rw = layers.zones[layers.zones["zone_type"] == "runway"]
    return rw.union_all(), layers.runway_lines


def _near_runway_nodes(layers, net, lo=20.0, hi=80.0):
    """Vehicle nodes whose distance to a runway zone edge is in [lo, hi] m, nearest first."""
    rw, _ = _runway_points(layers)
    nodes, arr = net.nodes_array()
    d = shapely.distance(shapely.points(arr[:, 0], arr[:, 1]), rw)
    order = np.argsort(d)
    return [(nodes[i], float(d[i])) for i in order if lo <= d[i] <= hi]


def _target_on_runway(layers, x, y):
    _, lines = _runway_points(layers)
    pt = Point(x, y)
    near = lines.geometry.iloc[int(np.argmin(lines.distance(pt)))]
    q = near.interpolate(near.project(pt))
    lon, lat = layers.to_wgs84([q.x], [q.y])
    return float(lat[0]), float(lon[0])


def _sector_cell(layers, net):
    """The H3 cell (APRON.h3_res) holding the most apron vehicle nodes."""
    apron = _anchors(layers)["apron_vnodes"]
    xy = np.array([net.xy[n] for n in apron])
    lon, lat = layers.to_wgs84(xy[:, 0], xy[:, 1])
    cells = [
        h3.latlng_to_cell(a, b, params.APRON.h3_res)
        for a, b in zip(lat, lon, strict=True)
    ]
    best = pd.Series(cells).value_counts().index[0]
    members = [n for n, c in zip(apron, cells, strict=True) if c == best]
    return best, members


def build(layers=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    layers = layers or MapLayers.load()
    rng = np.random.default_rng([params.SEED, DEMO_SEED, 99])
    net = nets(layers)["vehicle"]
    cell, parking = _sector_cell(layers, net)
    clat, clon = h3.cell_to_latlng(cell)
    cx, cy = layers.to_metric([clon], [clat])
    cx, cy = float(cx[0]), float(cy[0])

    # two runway-side nodes far from each other and from the sector
    cand = [
        (n, d)
        for n, d in _near_runway_nodes(layers, net)
        if np.hypot(*(np.array(net.xy[n]) - (cx, cy))) > 600
    ]
    tractor_node = cand[0][0]
    truck_node = next(
        n
        for n, _ in cand
        if np.hypot(*(np.array(net.xy[n]) - net.xy[tractor_node])) > 400
    )

    nodes, arr = net.nodes_array()
    near_sector = [
        n
        for n, (x, y) in zip(nodes, arr, strict=True)
        if 200 < np.hypot(x - cx, y - cy) < 700
    ]
    scripted = {
        ("vehicle", 0): {
            "asset_class": "baggage_tractor",
            "start": tractor_node,
            "stops": [(tractor_node, PHANTOM[0] + PHANTOM[1] + 40)],
        },
        ("vehicle", 1): {
            "asset_class": "fuel_truck",
            "start": truck_node,
            "stops": [(truck_node, 400.0)],
        },
    }
    parked_classes = (
        "catering_truck",
        "bus",
        "baggage_tractor",
        "catering_truck",
        "follow_me",
    )
    for k in range(N_PARKED):
        scripted[("vehicle", 2 + k)] = {
            "asset_class": parked_classes[k],
            "start": near_sector[int(rng.integers(len(near_sector)))],
            "stops": [(parking[k % len(parking)], DURATION_S)],
        }
    pts = build_assets(
        layers,
        rng,
        seed=DEMO_SEED,
        t0=T0,
        duration_s=DURATION_S,
        n_vehicles=N_VEHICLES,
        n_aircraft=N_AIRCRAFT,
        scene_id=SCENE_ID,
        scripted=scripted,
        center=parking[0],
        full_span=True,
    )
    pts["track_id"] = "demo:" + pts["asset_id"] + ":0"
    pts["base_track_id"] = pts["track_id"]
    pts["source"] = "demo"
    ids = pts[
        "track_id"
    ].unique()  # assets are concatenated in index order: vehicle 0, 1, ...

    tx, ty = net.xy[tractor_node]
    plat, plon = _target_on_runway(layers, tx, ty)
    bx, by = net.xy[truck_node]
    rlat, rlon = _target_on_runway(layers, bx, by)
    rw, _ = _runway_points(layers)
    zone_wgs = shapely.transform(
        rw, lambda c: np.column_stack(layers.to_wgs84(c[:, 0], c[:, 1]))
    )

    v = 0.7 * float(envelopes().loc["fuel_truck", "max_ground_speed_mps"])
    blon, blat = layers.to_wgs84([bx], [by])
    _, _, d_in = Geod(ellps="WGS84").inv(blon[0], blat[0], rlon, rlat)
    travel = 1.5 * float(d_in) / v
    truck_dur = 2 * travel + TRUCK_ON_RUNWAY_S

    ring = np.asarray(Point(cx, cy).buffer(SECTOR_RADIUS_M, 32).exterior.coords)
    lon, lat = layers.to_wgs84(ring[:, 0], ring[:, 1])
    region = shapely.Polygon(np.column_stack([lon, lat]))

    plans = [
        {
            "event_id": "ev_phantom",
            "cause": "technical_error",
            "onset_t": T0 + PHANTOM[0],
            "duration_s": PHANTOM[1],
            "track_ids": [ids[0]],
            "params": {"mode": "jump", "target_lat": plat, "target_lon": plon},
        },
        {
            "event_id": "ev_real",
            "cause": "behavioral_anomaly",
            "onset_t": T0 + TRUCK_START,
            "duration_s": truck_dur,
            "track_ids": [ids[1]],
            "params": {
                "mode": "incursion",
                "target_lat": rlat,
                "target_lon": rlon,
                "speed_mps": v,
                "zone_wkt": zone_wgs.wkt,
            },
        },
        {
            "event_id": "ev_sector",
            "cause": "possible_interference",
            "onset_t": T0 + SECTOR[0],
            "duration_s": SECTOR[1],
            "region": region,
            "params": {"radius_m": SECTOR_RADIUS_M, "h3_cell": cell},
        },
    ]
    pts, events = run_events(
        pts, plans, scene_id=SCENE_ID, seed=DEMO_SEED, layers=layers
    )
    return finalize(pts), events


def check(points: pd.DataFrame, events: pd.DataFrame) -> list[str]:
    """Scene requirements the script relies on; returns human-readable problems."""
    problems = []
    ev = events.set_index("event_id").sort_values("t_onset")
    gaps = ev["t_onset"].to_numpy()[1:] - ev["t_end"].to_numpy()[:-1]
    if (gaps < 90).any():
        problems.append(f"gaps between events {gaps}")
    sec = ev.loc["ev_sector"]
    g = points[
        points["track_id"].isin(sec["track_ids"])
        & (points["t"] >= sec["t_onset"])
        & (points["t"] < sec["t_end"])
    ]
    cells = g.apply(
        lambda r: h3.latlng_to_cell(
            r["label_true_lat"], r["label_true_lon"], params.APRON.h3_res
        ),
        axis=1,
    )
    whole = cells.groupby(g["track_id"]).agg(
        lambda c: c.nunique() == 1 and c.iloc[0] == sec_cell(sec)
    )
    if whole.sum() < 4:
        problems.append(f"only {whole.sum()} tracks stay in the sector cell")
    if len(sec["track_ids"]) < 5:
        problems.append(f"ev_sector hits {len(sec['track_ids'])} tracks")
    span = points.groupby("track_id")["t"].agg(["min", "max"])
    t0, t1 = points["t"].min(), points["t"].max()
    late = span[(span["min"] > t0 + 3) | (span["max"] < t1 - 3)]
    if len(late):
        problems.append(f"{len(late)} tracks do not span the scene")
    return problems


def sec_cell(row) -> str:
    return json.loads(row["params_json"])["h3_cell"]


def main() -> None:
    points, events = build()
    problems = check(points, events)
    POINTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    points.to_parquet(POINTS, index=False)
    events.to_parquet(EVENTS, index=False)
    print(
        events[["event_id", "cause", "t_onset", "t_end", "track_ids"]]
        .assign(t_onset=lambda e: e.t_onset - T0, t_end=lambda e: e.t_end - T0)
        .to_string()
    )
    print(f"points {len(points)}, tracks {points['track_id'].nunique()}")
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
