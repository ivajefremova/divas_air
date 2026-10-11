"""Believable baseline traffic for the fake replay scenarios.

Aircraft push back from real stands, taxi the taxiway network of map/fco_routes.graphml to a holding
point and line up; arrivals vacate a runway and taxi to a stand. Vehicles run service jobs on the
service-road network (stand visits with dwell times), buses shuttle, follow-me cars use taxiways.
Everything is in UTM 33N metres; positions are converted to lon/lat when the verdicts are written.
"""

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from divas_air import config as C  # noqa: E402

to_ll = Transformer.from_crs(C.CRS_METRIC, C.CRS_WGS84, always_xy=True).transform
to_utm = Transformer.from_crs(C.CRS_WGS84, C.CRS_METRIC, always_xy=True).transform

AIRLINES = ["ITY", "ITY", "ITY", "RYR", "RYR", "WZZ", "EZY", "VLG", "DLH", "AFR", "BAW", "UAE", "KLM", "IBE", "AEE", "TAP"]
WIDEBODY_AIRLINES = {"UAE", "ITY", "DLH"}


def layer(name):
    return json.loads((C.LAYERS / f"{name}.geojson").read_text())["features"]


# --- airport model ---------------------------------------------------------------------

class Airport:
    def __init__(self):
        G = nx.read_graphml(C.ROOT / "map" / "fco_routes.graphml")
        self.xy = {n: (float(d["x"]), float(d["y"])) for n, d in G.nodes(data=True)}
        self.graphs = {}
        for kind in ("taxiway", "service_road"):
            g = nx.Graph()
            for u, v, d in G.edges(data=True):
                if d.get("layer") != kind:
                    continue
                pts = [tuple(map(float, p.split())) for p in d["geometry"].split("(", 1)[1].rstrip(")").split(",")]
                if not g.has_edge(u, v) or g[u][v]["w"] > float(d["length_m"]):
                    g.add_edge(u, v, w=float(d["length_m"]), pts=pts, ref=d.get("ref"))
            big = max(nx.connected_components(g), key=len)
            self.graphs[kind] = g.subgraph(big).copy()
        self.runways = {}
        for f in layer("runway_areas"):
            poly = transform(to_utm, shape(f["geometry"]))
            box = poly.minimum_rotated_rectangle.exterior.coords
            sides = sorted([LineString([box[i], box[i + 1]]) for i in range(4)], key=lambda s: s.length)
            axis = LineString([sides[0].interpolate(0.5, normalized=True), sides[1].interpolate(0.5, normalized=True)])
            ref = f["properties"]["ref"]
            self.runways[ref] = dict(poly=poly, axis=axis, id="rwy_" + ref.replace("/", "_"), label=f"Runway {ref}")
        self.aprons = [dict(poly=transform(to_utm, shape(f["geometry"])), ref=f["properties"].get("ref")) for f in layer("aprons")]
        self.stands = [dict(ref=f["properties"]["ref"], xy=to_utm(*f["geometry"]["coordinates"][:2]))
                       for f in layer("stands") if f["geometry"]["type"] == "Point"]
        self.holds = [to_utm(*f["geometry"]["coordinates"][:2]) for f in layer("holding_points") if f["geometry"]["type"] == "Point"]
        lat0, lon0, lat1, lon1 = C.AIRPORT_BOX
        self.buildings, self.terminals = [], []
        for f in layer("buildings"):
            g = f.get("geometry")
            if not g:
                continue
            c = shape(g).centroid
            if not (lon0 <= c.x <= lon1 and lat0 <= c.y <= lat1):
                continue
            poly = transform(to_utm, shape(g))
            pr = f["properties"]
            b = dict(poly=poly, name=pr.get("name"), aeroway=pr.get("aeroway"))
            self.buildings.append(b)
            if pr.get("aeroway") == "terminal" and pr.get("name"):
                self.terminals.append(b)
        self._near = {}

    def nearest(self, kind, xy):
        g = self.graphs[kind]
        key = (kind, round(xy[0]), round(xy[1]))
        if key not in self._near:
            self._near[key] = min(g.nodes, key=lambda n: (self.xy[n][0] - xy[0]) ** 2 + (self.xy[n][1] - xy[1]) ** 2)
        return self._near[key]

    def route(self, kind, a, b) -> LineString | None:
        """Shortest path between two nodes as one line following the edge geometry."""
        g = self.graphs[kind]
        try:
            nodes = nx.shortest_path(g, a, b, weight="w")
        except nx.NetworkXNoPath:
            return None
        pts = [self.xy[nodes[0]]]
        for u, v in zip(nodes, nodes[1:]):
            seg = g[u][v]["pts"]
            if math.dist(seg[0], self.xy[u]) > math.dist(seg[-1], self.xy[u]):
                seg = seg[::-1]
            pts += seg[1:]
        return LineString(pts) if len(pts) > 1 else None

    def zone_of(self, xy, domain, airborne=False):
        """(zone_id, zone_name, criticality 0-1) for severity; runway > apron > taxiway > road."""
        if airborne:
            return "final", "Final approach", 1.0
        p = Point(xy)
        for r in self.runways.values():
            if r["poly"].buffer(25).contains(p):
                return r["id"], r["label"], 1.0
        for i, a in enumerate(self.aprons):
            if a["poly"].contains(p):
                return f"apron_{a['ref'] or i}", f"Apron {a['ref']}" if a["ref"] else "Apron", 0.5
        if domain == "aircraft":
            return "twy", "Taxiway", 0.5
        return "road", "Service road", 0.2

    def apron_name(self, xy):
        for t in sorted(self.terminals, key=lambda t: t["poly"].distance(Point(xy))):
            return t["name"]
        return "Apron"


# --- motion ------------------------------------------------------------------------------

@dataclass
class Segment:
    t0: float
    t1: float
    line: LineString | None = None      # None = standing still at `xy`
    xy: tuple = (0.0, 0.0)
    v0: float = 0.0                     # speed profile: accelerate v0 -> v1 over the segment
    v1: float = 0.0
    course: float = 0.0


def course_at(line, s):
    s = min(max(s, 0.0), line.length)
    a, b = line.interpolate(max(s - 2, 0)), line.interpolate(min(s + 2, line.length))
    return math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360


@dataclass
class Track:
    track_id: str
    domain: str
    asset_class: str
    callsign: str | None
    segments: list = field(default_factory=list)
    airborne_until: float = -1.0       # aircraft on final: alt > 0 before this time
    alt_profile: tuple | None = None    # (t_touchdown, descent m/s)
    t_end: float | None = None          # track disappears after (take-off)

    def add_still(self, t0, t1, xy, course):
        self.segments.append(Segment(t0, t1, None, xy, 0, 0, course))
        return t1

    def add_drive(self, t0, line, v0, v1=None):
        v1 = v0 if v1 is None else v1
        dur = line.length / max((v0 + v1) / 2, 0.5)
        self.segments.append(Segment(t0, t0 + dur, line, (0, 0), v0, v1))
        return t0 + dur

    def state(self, t):
        """(xy, course, speed) at time t, holding the last state after the final segment."""
        seg = next((s for s in self.segments if s.t0 <= t <= s.t1), None)
        if seg is None:
            seg = self.segments[-1] if t > self.segments[-1].t1 else self.segments[0]
            t = seg.t1 if t > seg.t1 else seg.t0
        if seg.line is None:
            return seg.xy, seg.course, 0.0
        dur = max(seg.t1 - seg.t0, 1e-6)
        f = (t - seg.t0) / dur
        v = seg.v0 + (seg.v1 - seg.v0) * f
        s = (seg.v0 * f + (seg.v1 - seg.v0) * f * f / 2) * dur
        p = seg.line.interpolate(min(s, seg.line.length))
        return (p.x, p.y), course_at(seg.line, s), v

    def alt(self, t):
        if not self.alt_profile:
            return None
        t_td, rate = self.alt_profile
        return max(0.0, (t_td - t) * rate) if t < t_td else None

    def active(self, t):
        return self.t_end is None or t <= self.t_end


def callsign(rng, used):
    while True:
        al = AIRLINES[rng.integers(len(AIRLINES))]
        cs = f"{al}{rng.integers(10, 999)}{'' if rng.random() < .6 else 'ABCDEFGHJK'[rng.integers(10)]}"
        if cs not in used:
            used.add(cs)
            return cs, al


def hex_id(rng, used):
    while True:
        h = "".join("0123456789abcdef"[rng.integers(16)] for _ in range(6))
        if h not in used:
            used.add(h)
            return h


# --- baseline scene ----------------------------------------------------------------------

def baseline(ap: Airport, t0: float, duration: float, seed: int = 11, n_dep=5, n_arr=3, n_parked=7, n_vehicles=34):
    """A believable afternoon on the aprons: departures, arrivals, parked aircraft, service vehicles."""
    rng = np.random.default_rng(seed)
    used_cs, used_hex, tracks = set(), set(), []
    t_end = t0 + duration
    stands = [s for s in ap.stands]
    rng.shuffle(stands)
    holds = [h for h in ap.holds if any(r["poly"].distance(Point(h)) < 120 for r in ap.runways.values())]

    def aircraft(cls=None):
        cs, al = callsign(rng, used_cs)
        cls = cls or ("widebody" if al in WIDEBODY_AIRLINES and rng.random() < .5 else
                      "regional" if rng.random() < .12 else "narrowbody")
        return Track(f"fco:{hex_id(rng, used_hex)}:0", "aircraft", cls, cs)

    # departures: pushback, engine start, taxi to a holding point, wait, line up
    for k in range(n_dep):
        st = stands.pop()
        tr = aircraft()
        a = ap.nearest("taxiway", st["xy"])
        hold = holds[rng.integers(len(holds))]
        line = ap.route("taxiway", a, ap.nearest("taxiway", hold))
        if line is None or line.length < 300:
            continue
        push = LineString([st["xy"], ap.xy[a]])
        t = t0 - rng.uniform(0, 300)  # some are already taxiing when the scene starts
        t = tr.add_drive(t, push, 1.2)
        t = tr.add_still(t, t + rng.uniform(20, 50), ap.xy[a], course_at(push, push.length))
        t = tr.add_drive(t, line, 7.5 + rng.uniform(-1.5, 1.5))
        tr.add_still(t, t_end + 60, line.coords[-1], course_at(line, line.length))
        tracks.append(tr)

    # arrivals: vacate the runway, taxi to a stand, park
    for k in range(n_arr):
        st = stands.pop()
        tr = aircraft()
        rw = list(ap.runways.values())[rng.integers(len(ap.runways))]
        exit_pt = rw["axis"].interpolate(rng.uniform(0.35, 0.75), normalized=True)
        line = ap.route("taxiway", ap.nearest("taxiway", (exit_pt.x, exit_pt.y)), ap.nearest("taxiway", st["xy"]))
        if line is None or line.length < 300:
            continue
        t = t0 - rng.uniform(0, line.length / 8 - 30)
        t = tr.add_drive(t, line, 8.0 + rng.uniform(-1, 1))
        t = tr.add_drive(t, LineString([line.coords[-1], st["xy"]]), 2.5, 0.3)
        tr.add_still(t, t_end + 60, st["xy"], course_at(line, line.length))
        tracks.append(tr)

    # parked aircraft with transponder on (APU, boarding)
    for k in range(n_parked):
        st = stands.pop()
        tr = aircraft()
        tr.add_still(t0 - 60, t_end + 60, st["xy"], float(rng.uniform(0, 360)))
        tracks.append(tr)

    # service vehicles: stand jobs on the service-road network
    classes = (["baggage_tractor"] * 11 + ["bus"] * 6 + ["fuel_truck"] * 5 + ["catering_truck"] * 5
               + ["follow_me"] * 3 + ["sar_vehicle"] * 1 + ["baggage_tractor"] * 3)
    service_stands = [s for s in ap.stands]
    for k in range(min(n_vehicles, len(classes))):
        cls = classes[k]
        vid = f"veh_{100 + k:03d}"
        tr = Track(f"synthetic:{vid}:0", "vehicle", cls, None)
        kind = "taxiway" if cls == "follow_me" else "service_road"
        t = t0 - rng.uniform(0, 240)
        node = ap.nearest(kind, service_stands[rng.integers(len(service_stands))]["xy"])
        if cls == "sar_vehicle":  # standing by at its station
            tr.add_still(t0 - 60, t_end + 60, ap.xy[node], float(rng.uniform(0, 360)))
            tracks.append(tr)
            continue
        speed = {"bus": 8.5, "fuel_truck": 6.5, "catering_truck": 6.0, "follow_me": 10.0}.get(cls, 7.0)
        while t < t_end + 30:
            dest = ap.nearest(kind, service_stands[rng.integers(len(service_stands))]["xy"])
            line = ap.route(kind, node, dest)
            if line is None or line.length < 120 or line.length > 2600:
                continue
            t = tr.add_drive(t, line, speed + rng.uniform(-1, 1))
            dwell = rng.uniform(60, 180) if cls != "bus" else rng.uniform(25, 60)
            t = tr.add_still(t, t + dwell, line.coords[-1], course_at(line, line.length))
            node = dest
        tracks.append(tr)
    return tracks, rng


def approach_track(ap: Airport, rng, used_hex, used_cs, runway_ref, t_touchdown, cs=None):
    """An aircraft on final approach to `runway_ref` (landing from the north end), touching down at t_touchdown."""
    rw = ap.runways[runway_ref]
    a, b = rw["axis"].coords[0], rw["axis"].coords[-1]
    north, south = (a, b) if a[1] > b[1] else (b, a)
    ux, uy = north[0] - south[0], north[1] - south[1]
    n = math.hypot(ux, uy)
    ux, uy = ux / n, uy / n
    start = (north[0] + ux * 14000, north[1] + uy * 14000)
    final = LineString([start, north])
    roll = LineString([north, (north[0] - ux * 1600, north[1] - uy * 1600)])
    cs_, _ = (cs, None) if cs else callsign(rng, used_cs)
    tr = Track(f"fco:{hex_id(rng, used_hex)}:0", "aircraft", "narrowbody", cs_)
    v = 72.0
    t_start = t_touchdown - final.length / v
    t = tr.add_drive(t_start, final, v)
    t = tr.add_drive(t, roll, v, 20.0)
    tr.add_still(t, t + 600, roll.coords[-1], course_at(roll, roll.length))
    tr.alt_profile = (t_touchdown, 0.052 * v)  # ~3 degree glide path
    return tr
