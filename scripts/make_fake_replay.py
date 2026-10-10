"""Fake replay bundle for building the map before module 6 exists.

Writes data/processed/demo/replay_fake/manifest.json and frames.jsonl: the same files and shapes as
`python -m divas_air.api.replay` (contract.ReplayManifest, one contract.ReplayFrame per line), every
line validated against src/divas_air/contract.py. Event ids, times and track ids follow
contracts/examples/replay_manifest.json, so the map reads the real bundle (replay/) unchanged.

Vehicles drive the service roads and aircraft the taxiways of map/fco_routes.graphml. The scores are
scripted, not modelled; states, smoothing, confidence levels and severity follow params.py.

    python scripts/make_fake_replay.py
"""

import json
import math
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from divas_air import config as C  # noqa: E402
from divas_air import contract as K  # noqa: E402
from divas_air import params as P  # noqa: E402
from divas_air.schema import CAUSES  # noqa: E402

OUT = C.PROCESSED / "demo" / "replay_fake"
T0, DURATION, STEP = 1791899700.0, 600, P.REPLAY_STEP_S
TIMES = [T0 + k * STEP for k in range(DURATION // STEP + 1)]
EVENTS = [  # as in contracts/examples/replay_manifest.json
    dict(event_id="ev_phantom", kind="phantom_incursion", title="Phantom runway incursion",
         t_start=T0 + 100, t_end=T0 + 160, track_ids=["synthetic:veh_017:0"]),
    dict(event_id="ev_real", kind="real_incursion", title="Real runway incursion",
         t_start=T0 + 250, t_end=T0 + 310, track_ids=["synthetic:veh_031:0"]),
    dict(event_id="ev_sector", kind="sector_interference", title="Sector interference",
         t_start=T0 + 400, t_end=T0 + 550, track_ids=["synthetic:veh_044:0", "synthetic:veh_045:0", "synthetic:veh_052:0"]),
]
SECTOR_MEMBERS = EVENTS[2]["track_ids"]
LATE_MEMBER, LATE_ENTRY = "synthetic:veh_061:0", T0 + 470  # warned first, then joins the area alert

rng = np.random.default_rng(7)
to_ll = Transformer.from_crs(C.CRS_METRIC, C.CRS_WGS84, always_xy=True).transform
to_utm = Transformer.from_crs(C.CRS_WGS84, C.CRS_METRIC, always_xy=True).transform

ACTIONS = {
    "none": "No action.",
    "monitor": "Keep watching: position accuracy is reduced.",
    "verify_radio": "Verify the vehicle's position by radio before holding the runway.",
    "act_now": "Act now: position data is sound and the vehicle is on the runway.",
    "area_gnss_unreliable": "GNSS is unreliable on Apron E: confirm positions visually.",
}


# --- map ---------------------------------------------------------------------------------

def load_layer(name):
    return json.loads((C.LAYERS / f"{name}.geojson").read_text())["features"]


RUNWAYS = {}
for f in load_layer("runways"):
    name = f["properties"]["runway"]
    poly = transform(to_utm, shape(f["geometry"]))
    box = poly.minimum_rotated_rectangle.exterior.coords
    sides = sorted([LineString([box[i], box[i + 1]]) for i in range(4)], key=lambda s: s.length)
    axis = LineString([sides[0].interpolate(0.5, normalized=True), sides[1].interpolate(0.5, normalized=True)])
    RUNWAYS[name] = dict(poly=poly, axis=axis, id="rwy_" + name.replace("/", "_"), label=f"Runway {name}")

APRONS = [dict(poly=transform(to_utm, shape(f["geometry"])), ref=f["properties"].get("ref")) for f in load_layer("aprons")]
APRON_E = min(APRONS, key=lambda a: a["poly"].centroid.distance(Point(to_utm(12.2559, 41.7976))))
APRON_E["ref"] = "E"

G = nx.read_graphml(C.ROOT / "map" / "fco_routes.graphml")
XY = {n: (float(d["x"]), float(d["y"])) for n, d in G.nodes(data=True)}


def edge_xy(u, v, d):
    pts = [tuple(map(float, p.split())) for p in d["geometry"].split("(", 1)[1].rstrip(")").split(",")]
    return pts if math.dist(pts[0], XY[u]) <= math.dist(pts[-1], XY[u]) else pts[::-1]


def walk(start, kind, length_m):
    """Random walk on edges of one kind (taxiway | service_road), no U-turns unless at a dead end."""
    pts, node, prev, total = [XY[start]], start, None, 0.0
    while total < length_m:
        opts = [(v, d) for _, v, d in G.edges(node, data=True) if d.get("layer") == kind]
        fwd = [o for o in opts if o[0] != prev] or opts
        if not fwd:
            break
        v, d = fwd[rng.integers(len(fwd))]
        seg = edge_xy(node, v, d)
        pts += seg[1:]
        total += float(d["length_m"])
        prev, node = node, v
    return LineString(pts)


def nodes_near(kind, x, y, r):
    return [n for n in G.nodes if any(d.get("layer") == kind for *_, d in G.edges(n, data=True))
            and math.dist(XY[n], (x, y)) < r]


def at(line: LineString, s: float):
    """Position and course (deg from north) at distance s along a line."""
    s = min(max(s, 0.0), line.length)
    p, q = line.interpolate(s), line.interpolate(min(s + 3, line.length))
    if q.distance(p) < 0.1:
        q, p = p, line.interpolate(max(s - 3, 0))
    return (p.x, p.y), math.degrees(math.atan2(q.x - p.x, q.y - p.y)) % 360


# --- tracks ------------------------------------------------------------------------------

VEHICLE_CLASSES = ["baggage_tractor", "bus", "fuel_truck", "catering_truck", "follow_me", "baggage_tractor", "bus"]
AIRCRAFT = [("4ca7b5", "RYR4TK", "narrowbody"), ("4d2101", "WMT6KP", "narrowbody"), ("3c6589", "DLH5MM", "narrowbody"),
            ("400a1f", "EZY81QF", "narrowbody"), ("4b1814", "SWR1739", "narrowbody"), ("ab42f1", "AAL719", "widebody"),
            ("06a0d2", "QTR132", "widebody"), ("4ca9c3", "EIN4KC", "regional")]
TERMINAL = to_utm(12.2505, 41.7965)


class Track:
    def __init__(self, track_id, domain, asset_class, callsign, path_fn):
        self.track_id, self.domain, self.asset_class, self.callsign = track_id, domain, asset_class, callsign
        self.asset_id = track_id.split(":")[1]
        self.path_fn = path_fn  # t -> ((x, y), course_deg, speed_mps)


def moving(line, speed, t_start=T0, s0=0.0):
    def f(t):
        s = s0 + max(t - t_start, 0) * speed
        if line.length and s > line.length:  # bounce back and forth along the line
            s = line.length - abs((s % (2 * line.length)) - line.length)
        p, c = at(line, s)
        return p, c, speed
    return f


tracks = []
service_start = nodes_near("service_road", *TERMINAL, 1500)
taxi_start = nodes_near("taxiway", *TERMINAL, 2200)

# background vehicles (veh_0xx not used by events)
special = {17, 31, 44, 45, 52, 61}
ids = [i for i in range(10, 70) if i not in special][:20]
for k, i in enumerate(ids):
    sp = float(rng.uniform(4, 8))
    line = walk(service_start[rng.integers(len(service_start))], "service_road", sp * DURATION + 200)
    tracks.append(Track(f"synthetic:veh_{i:03d}:0", "vehicle", VEHICLE_CLASSES[k % len(VEHICLE_CLASSES)], None,
                        moving(line, sp)))

for hexid, cs, cls in AIRCRAFT:
    sp = float(rng.uniform(5, 8))
    line = walk(taxi_start[rng.integers(len(taxi_start))], "taxiway", sp * DURATION + 200)
    tracks.append(Track(f"fco:{hexid}:0", "aircraft", cls, cs, moving(line, sp)))

# ev_phantom: a tractor driving east of runway 16R/34L; its reported position jumps onto the runway
r16r = RUNWAYS["16R/34L"]
start = min(nodes_near("service_road", *r16r["axis"].interpolate(0.55, normalized=True).coords[0], 900),
            key=lambda n: abs(r16r["axis"].distance(Point(XY[n])) - 300))
phantom_line = walk(start, "service_road", 6 * DURATION + 200)
tracks.append(Track("synthetic:veh_017:0", "vehicle", "baggage_tractor", None, moving(phantom_line, 5.5)))

# ev_real: a fuel truck drives onto runway 16L/34R, along it, and back
r16l = RUNWAYS["16L/34R"]
gate = min(nodes_near("service_road", *r16l["axis"].interpolate(0.25, normalized=True).coords[0], 1500),
           key=lambda n: r16l["axis"].distance(Point(XY[n])))
lengths = nx.single_source_dijkstra_path_length(
    G.edge_subgraph([(u, v, k) for u, v, k, d in G.edges(keys=True, data=True) if d.get("layer") == "service_road"]),
    gate, weight="length_m")
far = min(lengths, key=lambda n: abs(lengths[n] - 1100))
sub = nx.Graph((u, v, {"w": d["length_m"]}) for u, v, d in G.edges(data=True) if d.get("layer") == "service_road")
route = nx.shortest_path(sub, far, gate, weight="w")
approach = LineString([XY[n] for n in route])
on_rwy = r16l["axis"].interpolate(r16l["axis"].project(Point(XY[gate])))
along = r16l["axis"].interpolate(r16l["axis"].project(on_rwy) + 280)
excursion = LineString([XY[gate], on_rwy.coords[0], along.coords[0], XY[gate]])


def real_path(t, v=7.0):
    t_arrive = T0 + 240  # reaches the runway edge 10 s before onset
    if t < t_arrive:
        p, c = at(approach, approach.length - (t_arrive - t) * v)
        return p, c, v if t > t_arrive - approach.length / v else 0.0
    p, c = at(excursion, (t - t_arrive) * 6.0)
    moving_now = (t - t_arrive) * 6.0 < excursion.length
    return p, c, 6.0 if moving_now else 0.0


tracks.append(Track("synthetic:veh_031:0", "vehicle", "fuel_truck", None, real_path))

# ev_sector: three vehicles driving the inner edge of Apron E, and one heading into it
inner = APRON_E["poly"].buffer(-12)
inner = inner if inner.geom_type == "Polygon" else max(inner.geoms, key=lambda g: g.area)
RING = LineString(inner.exterior.coords)
SECTOR = APRON_E["poly"].buffer(60, quad_segs=8).simplify(5)  # the live interference area
ce = APRON_E["poly"].representative_point()


def loop(phase, speed=4.0):
    def f(t):
        p, c = at(RING, (phase * RING.length + (t - T0) * speed) % RING.length)
        return p, c, speed
    return f


for tid, ph in zip(SECTOR_MEMBERS, (0.0, 0.33, 0.66)):
    tracks.append(Track(tid, "vehicle", "bus" if tid.endswith("044:0") else "baggage_tractor", None, loop(ph)))

inbound_from = Point(ce.x + 520, ce.y - 200)
assert not SECTOR.contains(inbound_from)
inbound = LineString([inbound_from, ce])
INBOUND_SPEED = 5.0
_cross = inbound.project(inbound.intersection(SECTOR.exterior).geoms[0]
                         if hasattr(inbound.intersection(SECTOR.exterior), "geoms") else inbound.intersection(SECTOR.exterior))
INBOUND_START = LATE_ENTRY - _cross / INBOUND_SPEED  # crosses the area edge at LATE_ENTRY
tracks.append(Track(LATE_MEMBER, "vehicle", "catering_truck", None,
                    lambda t: (lambda p, c: (p, c, INBOUND_SPEED if t < LATE_ENTRY + 60 else 0.0))(
                        *at(inbound, min(max(t - INBOUND_START, 0) * INBOUND_SPEED, inbound.length - 30)))))


# --- scores ------------------------------------------------------------------------------

def ramp(t, t_on, t_off, rise=10):
    """0 outside [t_on, t_off], 1 inside, with a short ramp at onset."""
    if t < t_on or t > t_off:
        return 0.0
    return min(1.0, (t - t_on + STEP) / rise)


def probs(cause, p):
    """Calibrated-looking probabilities: `p` on the cause, the rest spread, exact sum 1 in thousandths."""
    rest = [c for c in CAUSES if c != cause]
    top = int(round(p * 1000))
    w = np.floor(rng.dirichlet(np.ones(len(rest))) * (1000 - top)).astype(int)
    w[0] += 1000 - top - w.sum()
    return {cause: top / 1000, **{c: int(x) / 1000 for c, x in zip(rest, w)}}


def scripted(tr: Track, t: float):
    """Raw (pre-smoothing) integrity, normality, dims, cause, evidence, action, confidence."""
    n = lambda lo, hi: float(rng.uniform(lo, hi))  # noqa: E731
    base = dict(integ=n(90, 99), norm=n(88, 100), dims=dict(kinetic=n(92, 100), temporal=n(90, 100), spatial=n(90, 100),
                contextual=n(92, 100)), cause="plausible", p=n(0.85, 0.95), evidence=[], action="none", conf=n(0.82, 0.95),
                area=None, warn=None)
    tid = tr.track_id
    if tid == "synthetic:veh_017:0" and (k := ramp(t, T0 + 100, T0 + 160)):
        base.update(integ=n(18, 30), norm=n(20, 32), cause="technical_error", p=n(0.62, 0.72), action="verify_radio", conf=n(0.78, 0.86),
                    dims=dict(kinetic=n(5, 15), temporal=n(80, 92), spatial=n(25, 35), contextual=n(8, 18)),
                    evidence=[ev("kin_speed_resid_max", "kinetic", "Position implies 41 m/s but the asset reports 6 m/s", 35, 10, "m/s"),
                              ev("kin_accel_imp_ratio_max", "kinetic", "Position implies an acceleration 6.2x the maximum for a baggage_tractor", 6.2, 1.5, "ratio"),
                              ev("ctx_type_violation_crit_max", "contextual", "A baggage_tractor is not authorized in Runway 16R/34L", 1, 0, "0-1")])
    elif tid == "synthetic:veh_031:0" and ramp(t, T0 + 250, T0 + 310):
        base.update(integ=n(88, 96), norm=n(12, 25), cause="behavioral_anomaly", p=n(0.8, 0.9), action="act_now", conf=n(0.86, 0.93),
                    dims=dict(kinetic=n(88, 98), temporal=n(90, 99), spatial=n(15, 25), contextual=n(5, 12)),
                    evidence=[ev("ctx_type_violation_crit_max", "contextual", "A fuel_truck is not authorized in Runway 16L/34R", 1, 0, "0-1"),
                              ev("spa_route_dist_max_m", "spatial", "54 m from the nearest authorized route", 54, 25, "m")])
    elif (tid in SECTOR_MEMBERS and ramp(t, T0 + 400, T0 + 550)) or (tid == LATE_MEMBER and ramp(t, LATE_ENTRY, T0 + 550)):
        gap = int(rng.integers(11, 18))
        base.update(integ=n(18, 32), norm=n(80, 92), cause="possible_interference", p=n(0.5, 0.6), action="area_gnss_unreliable",
                    conf=n(0.52, 0.66), area="area_0001",
                    dims=dict(kinetic=n(35, 55), temporal=n(30, 45), spatial=n(80, 92), contextual=n(85, 95)),
                    evidence=[ev("flt_deg_rate_loo", "fleet", "80% of other assets in this area are degraded at the same time", 0.8, None, "ratio"),
                              ev("tmp_gap_max_s", "temporal", f"No position for {gap} s", gap, 10, "s")])
    elif tid == "fco:4d2101:0" and ramp(t, T0 + 190, T0 + 225):
        base.update(integ=n(58, 66), cause="degraded", p=n(0.5, 0.6), action="monitor", conf=n(0.55, 0.7),
                    dims=dict(kinetic=n(70, 80), temporal=n(85, 95), spatial=n(88, 98), contextual=n(92, 100)),
                    evidence=[ev("sig_nacp_min", "signal", "Navigation accuracy category dropped to 6 (limit 8)", 6, 8, "category")])
    if tid == LATE_MEMBER and INBOUND_START <= t < LATE_ENTRY and t >= T0 + 400:
        base["warn"] = max(LATE_ENTRY - t, 0.0)
    return base


def ev(feature, dim, text, value, limit, unit):
    return dict(feature=feature, dimension=dim, text=text, value=value, limit=limit, unit=unit)


def zone_of(tr: Track, xy):
    p = Point(xy)
    for r in RUNWAYS.values():
        if r["poly"].buffer(P.ZONE_BUFFER_M / 2).contains(p):
            return r["id"], r["label"], P.CRITICALITY["high"]
    for a in APRONS:
        if a["poly"].contains(p):
            ref = a["ref"] or ""
            return ("apron_" + ref if ref else "apron"), ("Apron " + ref).strip(), P.CRITICALITY["medium"]
    if tr.domain == "aircraft":
        return "twy", "Taxiway", P.CRITICALITY["medium"]
    return "road", "Service road", P.CRITICALITY["low"]


def severity_level(score):
    return next((lvl for thr, lvl in P.SEVERITY_LEVELS if score >= thr), "none")


def conf_level(c):
    return "high" if c >= P.CONF_HIGH else "medium" if c >= P.CONF_MEDIUM else "low"


# --- assemble frames ---------------------------------------------------------------------

def reported(tr: Track, t, xy):
    """What the receiver reports: the true position, except during data events."""
    x, y = xy
    if tr.track_id == "synthetic:veh_017:0" and T0 + 100 <= t <= T0 + 160:
        q = r16r["axis"].interpolate(r16r["axis"].project(Point(xy)))  # phantom: snapped onto the runway
        return q.x + rng.normal(0, 4), q.y + rng.normal(0, 4)
    hit = (tr.track_id in SECTOR_MEMBERS and T0 + 400 <= t <= T0 + 550) or (tr.track_id == LATE_MEMBER and LATE_ENTRY <= t <= T0 + 550)
    if hit:
        return x + rng.normal(0, 18), y + rng.normal(0, 18)
    return x + rng.normal(0, 1.2), y + rng.normal(0, 1.2)


def static_halos():
    feats = []
    for rid, label, (lon, lat), r in [("static_T3", "Signal shadow: Terminal 3", (12.2495, 41.7995), 120),
                                      ("static_T1", "Signal shadow: Terminal 1", (12.2560, 41.8005), 100)]:
        c = Point(to_utm(lon, lat)).buffer(r, quad_segs=8)
        feats.append(dict(type="Feature", geometry=dict(type="Polygon", coordinates=[ll_ring(c.exterior.coords)]),
                          properties=dict(risk_zone_id=rid, kind="static", level=0.45, label=label, expected_error_m=8.0)))
    return feats


def ll_ring(coords):
    return [[round(a, 6) for a in to_ll(x, y)] for x, y in coords]


STATIC = static_halos()
smooth, trust, abn = {}, {}, {}


def step_state(tid, integ_raw, norm):
    prev = smooth.get(tid, integ_raw)
    a = P.EMA_ALPHA_DOWN if integ_raw < prev else P.EMA_ALPHA_UP
    s = a * integ_raw + (1 - a) * prev
    smooth[tid] = s
    st = trust.get(tid, "trusted")
    if st == "untrusted":
        st = "untrusted" if s <= P.UNTRUSTED_EXIT else ("caution" if s < P.CAUTION_EXIT else "trusted")
    elif st == "caution":
        st = "untrusted" if s < P.UNTRUSTED_ENTER else ("trusted" if s > P.CAUTION_EXIT else "caution")
    else:
        st = "untrusted" if s < P.UNTRUSTED_ENTER else ("caution" if s < P.CAUTION_ENTER else "trusted")
    trust[tid] = st
    ab = abn.get(tid, False)
    ab = norm <= P.ABNORMAL_EXIT if ab else norm < P.ABNORMAL_ENTER
    abn[tid] = ab
    return s, st, "abnormal" if ab else "expected"


def frame(t):
    verdicts, live_members = [], []
    for tr in tracks:
        xy, course, speed = tr.path_fn(t)
        rx, ry = reported(tr, t, xy)
        sc = scripted(tr, t)
        integ, st, ns = step_state(tr.track_id, sc["integ"], sc["norm"])
        cause = sc["cause"]
        if st == "trusted" and cause not in ("plausible", "behavioral_anomaly"):
            cause = "plausible"  # the reported cause never contradicts the state (00_contracts 5)
        if st == "untrusted" and cause == "plausible":
            cause = "technical_error"
        zid, zname, crit = zone_of(tr, (rx, ry))
        score = round(min(1.0, max(1 - integ / 100, 1 - sc["norm"] / 100) * crit), 3)
        lvl = severity_level(score)
        action = sc["action"] if lvl != "none" or sc["action"] == "monitor" else "none"
        if action == "monitor" and st == "trusted":
            action = "none"
        lon, lat = to_ll(rx, ry)
        area = sc["area"] if st == "untrusted" else None
        if area:
            live_members.append((tr.track_id, (rx, ry)))
        warn = None
        if sc["warn"] is not None:
            warn = dict(risk_zone_id="live_area_0001", eta_s=round(sc["warn"], 1))
        verdicts.append(dict(
            track_id=tr.track_id, asset_id=tr.asset_id, domain=tr.domain, asset_class=tr.asset_class, callsign=tr.callsign,
            t=t, window_s=C.WINDOW_S,
            position=dict(lat=round(lat, 6), lon=round(lon, 6), alt_m=None, track_deg=round(course, 1), speed_mps=round(speed, 1)),
            integrity=round(integ, 1), integrity_raw=round(sc["integ"], 1), normality=round(sc["norm"], 1),
            dimensions={k: round(v, 1) for k, v in sc["dims"].items()},
            trust_state=st, normality_state=ns, quadrant=K.quadrant_of(st, ns),
            confidence=round(sc["conf"], 2), confidence_level=conf_level(sc["conf"]),
            cause=cause, cause_probs=probs(cause, sc["p"]),
            severity=dict(level=lvl, score=score, zone_id=zid, zone_name=zname, zone_criticality=crit),
            evidence=sc["evidence"] if st != "trusted" or ns == "abnormal" else [],
            action=dict(code=action, text=ACTIONS[action]),
            area_alert_id=area, early_warning=warn))
    zones = list(STATIC)
    if len(live_members) >= 3:
        hull = SECTOR  # the affected sector around Apron E
        zones.append(dict(type="Feature", geometry=dict(type="Polygon", coordinates=[ll_ring(hull.exterior.coords)]),
                          properties=dict(risk_zone_id="live_area_0001", kind="live", level=0.85, label="Possible interference: Apron E",
                                          area_alert_id="area_0001", track_ids=[m for m, _ in live_members],
                                          action=dict(code="area_gnss_unreliable", text=ACTIONS["area_gnss_unreliable"]),
                                          t_start=EVENTS[2]["t_start"], t_end=EVENTS[2]["t_end"])))
        v61 = next(v for v in verdicts if v["track_id"] == LATE_MEMBER)
        if v61["early_warning"]:
            here = (v61["position"]["lon"], v61["position"]["lat"])
            edge = SECTOR.exterior
            hit = edge.interpolate(edge.project(Point(to_utm(*here))))
            zones.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=[list(here), [round(a, 6) for a in to_ll(hit.x, hit.y)]]),
                              properties=dict(risk_zone_id="forecast_veh_061", kind="forecast", level=0.85,
                                              label=f"veh_061 enters the interference area in {v61['early_warning']['eta_s']:.0f} s",
                                              track_ids=[LATE_MEMBER], enters_risk_zone_id="live_area_0001",
                                              eta_s=v61["early_warning"]["eta_s"], t_start=t, t_end=t + v61["early_warning"]["eta_s"])))
    return dict(t=t, verdicts=verdicts, risk_zones=dict(type="FeatureCollection", t=t, features=zones))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "frames.jsonl", "w") as fh:
        for t in TIMES:
            fr = K.ReplayFrame.model_validate(frame(t))  # contract check, every line
            fh.write(fr.model_dump_json() + "\n")
    man = K.ReplayManifest(airport="LIRF", t_start=TIMES[0], t_end=TIMES[-1], step_s=STEP, n_frames=len(TIMES),
                           events=[K.ReplayEvent(**e) for e in EVENTS])
    (OUT / "manifest.json").write_text(man.model_dump_json(indent=2))
    print(f"{len(TIMES)} frames, {len(tracks)} tracks -> {OUT} ({(OUT / 'frames.jsonl').stat().st_size // 1024} KB)")
