"""Ground scenes: assets on the route graph, nominal noise, random events (specs/02 sections 1-4)."""

from __future__ import annotations

from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point

from divas_air import config, params, schema
from divas_air.geo import MapLayers
from divas_air.synth.inject import add_labels, apply_event
from divas_air.synth.motion import RouteNet, drive, envelopes, report, sample_times

SOURCE = "synthetic"
VEHICLE_CLASSES = (
    "baggage_tractor",
    "bus",
    "fuel_truck",
    "catering_truck",
    "sar_vehicle",
    "follow_me",
)
VEHICLE_WEIGHTS = (0.35, 0.15, 0.15, 0.15, 0.05, 0.15)
AIRCRAFT_CLASSES = ("narrowbody", "widebody", "regional")
AIRCRAFT_WEIGHTS = (0.6, 0.25, 0.15)
NO_RUNWAY = (
    "baggage_tractor",
    "bus",
    "fuel_truck",
    "catering_truck",
)  # zone_access: runway not allowed
EVENT_CAUSES = (
    "degraded",
    "technical_error",
    "gnss_anomaly",
    "possible_interference",
    "possible_spoofing",
    "behavioral_anomaly",
)
EVENT_WEIGHTS = (0.17, 0.22, 0.17, 0.08, 0.2, 0.16)
EVENTS_PER_SCENE = ((0, 1, 2, 3), (0.34, 0.22, 0.24, 0.2))
EVENT_COLUMNS = [
    "event_id",
    "scene_id",
    "cause",
    "t_onset",
    "t_end",
    "track_ids",
    "region_wkt",
    "params_json",
]
POINT_COLUMNS = [
    "track_id",
    "asset_id",
    "source",
    "domain",
    "seq",
    "t",
    "lat",
    "lon",
    "asset_class",
    "type_overridden",
    "alt_baro_m",
    "alt_geom_m",
    "gs_mps",
    "track_deg",
    "heading_deg",
    "vrate_mps",
    "on_ground",
    "nacp",
    "nic",
    "sil",
    "callsign",
    "typecode",
    "typecode_raw",
    *schema.LABEL_COLUMNS,
]
TYPECODE = {"narrowbody": "A320", "widebody": "B77W", "regional": "E190"}


@lru_cache(maxsize=2)
def nets(layers: MapLayers) -> dict[str, RouteNet]:
    return {d: RouteNet.build(layers, d) for d in ("vehicle", "aircraft")}


@lru_cache(maxsize=2)
def _anchors(layers: MapLayers) -> dict:
    """Aircraft graph nodes next to stands and runway holding points; vehicle nodes on aprons."""
    net_a, net_v = nets(layers)["aircraft"], nets(layers)["vehicle"]
    st = gpd.read_file(config.LAYERS / "stands.geojson").to_crs(config.CRS_METRIC)
    hp = gpd.read_file(config.LAYERS / "holding_points.geojson").to_crs(
        config.CRS_METRIC
    )
    hp = hp[hp["holding_position:type"] == "runway"]
    stands = list(dict.fromkeys(net_a.nearest_node(p.x, p.y) for p in st.geometry))
    holds = list(dict.fromkeys(net_a.nearest_node(p.x, p.y) for p in hp.geometry))
    aprons = layers.zones[layers.zones["zone_type"] == "apron"].union_all()
    vnodes, varr = net_v.nodes_array()
    on_apron = shapely.contains_xy(aprons.buffer(30.0), varr[:, 0], varr[:, 1])
    return {
        "stands": stands,
        "holds": holds,
        "apron_vnodes": [n for n, ok in zip(vnodes, on_apron, strict=True) if ok],
    }


def scene_t0(seed: int) -> float:
    return params.SYNTH_T0 + (seed % 200_000) * params.SYNTH_SLOT_S


def asset_frame(
    cols: dict,
    *,
    track_id: str,
    asset_id: str,
    domain: str,
    asset_class: str,
    scene_id: str,
) -> pd.DataFrame:
    n = len(cols["t"])
    df = pd.DataFrame(cols)
    df["track_id"] = track_id
    df["asset_id"] = asset_id
    df["source"] = SOURCE
    df["domain"] = domain
    df["seq"] = np.arange(n, dtype="int64")
    df["asset_class"] = asset_class
    df["type_overridden"] = False
    df["alt_baro_m"] = np.nan  # ground: no altitude reported, as on fco ground fixes
    df["alt_geom_m"] = np.nan
    df["vrate_mps"] = np.nan
    df["on_ground"] = True
    tc = TYPECODE.get(asset_class)
    df["callsign"] = None
    df["typecode"] = tc
    df["typecode_raw"] = tc
    df["scene_id"] = scene_id
    df["base_track_id"] = track_id
    return add_labels(df)


def _hex_id(rng) -> str:
    return f"{int(rng.integers(0x300000, 0x4FFFFF)):06x}"


def build_assets(
    layers,
    rng,
    *,
    seed: int,
    t0: float,
    duration_s: float,
    n_vehicles: int,
    n_aircraft: int,
    scene_id: str,
    scripted: dict | None = None,
    center=None,
    full_span: bool = False,
) -> pd.DataFrame:
    """All assets of one scene, clean. `scripted` maps asset index -> forced stops (demo)."""
    nv = nets(layers)
    anchors = _anchors(layers)
    net_v, net_a = nv["vehicle"], nv["aircraft"]
    vnodes, varr = net_v.nodes_array()
    t1 = t0 + duration_s
    scripted = scripted or {}

    # vehicles work around one apron area per scene: ground ops cluster, so area events hit several assets
    if center is None:
        center = anchors["apron_vnodes"][
            int(rng.integers(len(anchors["apron_vnodes"])))
        ]
    cx, cy = net_v.xy[center]
    near = [
        n
        for n, (x, y) in zip(vnodes, varr, strict=True)
        if np.hypot(x - cx, y - cy) < params.WORK_RADIUS_M
    ]

    def pick_vehicle_dest(node, r):
        return near[int(r.integers(len(near)))]

    frames = []
    classes = list(VEHICLE_CLASSES) + list(
        rng.choice(VEHICLE_CLASSES, max(n_vehicles - 6, 0), p=VEHICLE_WEIGHTS)
    )
    for i in range(n_vehicles):
        spec = scripted.get(("vehicle", i), {})
        cls = spec.get("asset_class", classes[i % len(classes)])
        start = spec.get("start", near[int(rng.integers(len(near)))])
        lead = 0.0 if spec else rng.uniform(0, 120)
        traj = drive(
            net_v,
            cls,
            rng,
            t_start=t0 - lead - 1.0,
            t_stop=t1 + 5.0,
            start_node=start,
            pick_dest=pick_vehicle_dest,
            stops=spec.get("stops"),
        )
        ts = sample_times(rng, "vehicle", t0, t1, full_span=full_span)
        asset_id = f"s{seed}v{i:02d}"
        frames.append(
            asset_frame(
                report(traj, ts, layers, rng),
                track_id=f"{SOURCE}:{asset_id}:g{seed}",
                asset_id=asset_id,
                domain="vehicle",
                asset_class=cls,
                scene_id=scene_id,
            )
        )

    for i in range(n_aircraft):
        spec = scripted.get(("aircraft", i), {})
        cls = spec.get(
            "asset_class", str(rng.choice(AIRCRAFT_CLASSES, p=AIRCRAFT_WEIGHTS))
        )
        outbound = rng.random() < 0.5
        a, b = anchors["stands"], anchors["holds"]
        if not outbound:
            a, b = b, a
        start = spec.get("start", a[int(rng.integers(len(a)))])
        dest = b[int(rng.integers(len(b)))]
        hold0 = rng.uniform(0, duration_s * 0.6)

        def pick_aircraft_dest(node, r, a=a, b=b):
            pool = b if node in a else a
            return pool[int(r.integers(len(pool)))]

        stops = spec.get("stops", [(start, hold0), (dest, rng.uniform(30, 120))])
        traj = drive(
            net_a,
            cls,
            rng,
            t_start=t0 - 1.0,
            t_stop=t1 + 5.0,
            start_node=start,
            pick_dest=pick_aircraft_dest,
            stops=stops,
            dwell=(30.0, 120.0),
            v_frac=(0.45, 0.7),
        )
        ts = sample_times(rng, "aircraft", t0, t1, full_span=full_span)
        asset_id = _hex_id(rng)
        frames.append(
            asset_frame(
                report(traj, ts, layers, rng),
                track_id=f"{SOURCE}:{asset_id}:g{seed}",
                asset_id=asset_id,
                domain="aircraft",
                asset_class=cls,
                scene_id=scene_id,
            )
        )

    return pd.concat(frames, ignore_index=True)


# --- random events -------------------------------------------------------------


def _true_xy(points: pd.DataFrame, layers):
    return layers.to_metric(
        points["label_true_lon"].to_numpy(), points["label_true_lat"].to_numpy()
    )


def _runway_distance(points: pd.DataFrame, layers) -> np.ndarray:
    x, y = _true_xy(points, layers)
    rw = layers.zones[layers.zones["zone_type"] == "runway"].union_all()
    return shapely.distance(shapely.points(x, y), rw)


def plan_event(
    points: pd.DataFrame, cause: str, slot: tuple[float, float], rng, layers, used: set
) -> dict | None:
    """Pick tracks, timing and region for one random event inside the time slot."""
    lo, hi = slot
    room = hi - lo
    tracks = [t for t in dict.fromkeys(points["track_id"]) if t not in used]
    if not tracks:
        return None
    if cause == "possible_interference":
        dur = min(rng.uniform(60, 180), room)
        onset = rng.uniform(lo, hi - dur)
        mid = points[(points["t"] >= onset) & (points["t"] < onset + dur)]
        x, y = _true_xy(mid, layers)
        best = None
        for _ in range(12):
            k = int(rng.integers(len(mid)))
            r = rng.uniform(150, 400)
            inside = np.hypot(x - x[k], y - y[k]) < r
            n = int((mid.loc[inside, "track_id"].value_counts() >= 3).sum())
            if n >= 3 and (best is None or n > best[0]):
                best = (n, x[k], y[k], r)
        if best is None:
            return None
        _, bx, by, r = best
        disk = Point(bx, by).buffer(r, 32)
        lon, lat = layers.to_wgs84(*np.asarray(disk.exterior.coords).T)
        region = shapely.Polygon(np.column_stack([lon, lat]))
        return {
            "cause": cause,
            "onset_t": onset,
            "duration_s": dur,
            "region": region,
            "params": {"radius_m": r},
        }

    classes = points.groupby("track_id")["asset_class"].first()
    if cause == "behavioral_anomaly":
        cand = [t for t in tracks if classes[t] in NO_RUNWAY]
        if cand:
            sub = points[
                points["track_id"].isin(cand)
                & (points["t"] >= lo)
                & (points["t"] < hi - 60)
            ]
            if len(sub):
                d = _runway_distance(sub, layers)
                k = int(np.argmin(d))
                if d[k] < 500.0 and rng.random() < 0.6:
                    tid = sub["track_id"].iloc[k]
                    onset = float(sub["t"].iloc[k])
                    v = 0.7 * float(
                        envelopes().loc[classes[tid], "max_ground_speed_mps"]
                    )
                    travel = 1.5 * (d[k] + params.RUNWAY_HALF_WIDTH_M) / v
                    dur = min(2 * travel + rng.uniform(30, 90), hi - onset)
                    return {
                        "cause": cause,
                        "onset_t": onset,
                        "duration_s": dur,
                        "track_ids": [tid],
                        "params": {"mode": "incursion"},
                    }
        tid = tracks[int(rng.integers(len(tracks)))]
        dur = min(rng.uniform(60, 200), room)
        return {
            "cause": cause,
            "onset_t": rng.uniform(lo, hi - dur),
            "duration_s": dur,
            "track_ids": [tid],
            "params": {"mode": "deviate"},
        }

    tid = tracks[int(rng.integers(len(tracks)))]
    dur = min(rng.uniform(60, 200), room)
    if cause == "technical_error":
        dur = min(rng.uniform(40, 120), room)
    return {
        "cause": cause,
        "onset_t": rng.uniform(lo, hi - dur),
        "duration_s": dur,
        "track_ids": [tid],
        "params": {},
    }


def run_events(
    points: pd.DataFrame, plans: list[dict], *, scene_id: str, seed: int, layers
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for j, ev in enumerate(plans):
        eid = ev.get("event_id") or f"{scene_id}_e{j}"
        points, info = apply_event(
            points,
            ev["cause"],
            onset_t=ev["onset_t"],
            duration_s=ev["duration_s"],
            track_ids=ev.get("track_ids"),
            region=ev.get("region"),
            params=ev.get("params"),
            seed=seed * 10 + j,
            event_id=eid,
            layers=layers,
        )
        if info["track_ids"]:
            rows.append({**info, "scene_id": scene_id})
    events = pd.DataFrame(rows, columns=EVENT_COLUMNS).astype(
        {"t_onset": "float64", "t_end": "float64"}
    )
    return points, events


def draw_events(points, rng, layers, *, t0: float, duration_s: float) -> list[dict]:
    n = int(rng.choice(EVENTS_PER_SCENE[0], p=EVENTS_PER_SCENE[1]))
    if n == 0:
        return []
    edges = np.linspace(t0 + 10.0, t0 + duration_s - 10.0, n + 1)
    plans, used = [], set()
    for k in range(n):
        cause = str(rng.choice(EVENT_CAUSES, p=EVENT_WEIGHTS))
        plan = plan_event(
            points, cause, (edges[k] + 5.0, edges[k + 1] - 5.0), rng, layers, used
        )
        if plan is None and cause == "possible_interference":
            plan = plan_event(
                points,
                "degraded",
                (edges[k] + 5.0, edges[k + 1] - 5.0),
                rng,
                layers,
                used,
            )
        if plan is not None:
            plans.append(plan)
            used.update(plan.get("track_ids") or [])
    return plans


def finalize(points: pd.DataFrame) -> pd.DataFrame:
    out = (
        points[POINT_COLUMNS]
        .sort_values(["track_id", "seq"], kind="stable")
        .reset_index(drop=True)
    )
    out = schema.coerce_points(out, labeled=True)
    schema.validate(out, labeled=True)
    return out


def generate_scene(
    seed: int,
    *,
    duration_s: float = 600.0,
    n_vehicles: int = 20,
    n_aircraft: int = 6,
    events: list[dict] | None = None,
    layers=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One ground scene: (labeled points, events). events=None draws events at random; [] gives a clean scene.

    An explicit event is a dict with `cause`, `onset_s` (seconds after the scene start)
    or `onset_t`, `duration_s`, and optionally `track_ids`, `region`, `params`, `event_id`.
    """
    layers = layers or MapLayers.load()
    rng = np.random.default_rng([params.SEED, seed])
    t0 = scene_t0(seed)
    scene_id = f"ground_{seed:06d}"
    pts = build_assets(
        layers,
        rng,
        seed=seed,
        t0=t0,
        duration_s=duration_s,
        n_vehicles=n_vehicles,
        n_aircraft=n_aircraft,
        scene_id=scene_id,
    )
    if events is None:
        plans = draw_events(pts, rng, layers, t0=t0, duration_s=duration_s)
    else:
        plans = [
            {**e, "onset_t": e.get("onset_t", t0 + e.get("onset_s", 0.0))}
            for e in events
        ]
    pts, ev = run_events(pts, plans, scene_id=scene_id, seed=seed, layers=layers)
    return finalize(pts), ev
