"""Fake replay scenario library for the web map (until module 6 delivers the real bundle).

SIMULATED DATA. Writes data/processed/demo/replay_fake/<scenario>/:
  manifest.json + frames.jsonl   module 6 format, every line validated against contract.ReplayFrame
  cameras.jsonl                  simulated partner-camera checks per frame (map-side sidecar)
  static_halos.geojson           graded signal-shadow bands around the terminals (display)
and replay_fake/index.json listing the scenarios with a title, a one-line story and the onset.

Traffic comes from scripts/fake_traffic.py (real stands, taxiways and service roads); each scenario
adds its actors and effects on top. Scores are scripted, not modelled; states, smoothing, confidence
levels and severity follow params.py and the reported cause never contradicts the state.

    python scripts/make_fake_replay.py
"""

import json
import math
import shutil
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from shapely.geometry import LineString, Point, mapping
from shapely.ops import substring, transform, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from divas_air import config as C  # noqa: E402
from divas_air import contract as K  # noqa: E402
from divas_air import params as P  # noqa: E402
from divas_air.schema import CAUSES  # noqa: E402
from fake_cameras import Coverage, build_cameras  # noqa: E402
from fake_traffic import Airport, Track, approach_track, baseline, course_at, to_ll  # noqa: E402

OUT = C.PROCESSED / "demo" / "replay_fake"
STEP = P.REPLAY_STEP_S
SCENE_S = 180
ONSET = 40          # seconds into the scene
DAY = 1792069200.0  # 2026-10-15 13:00 UTC (15:00 in Rome)
NIGHT = DAY + 9 * 3600


def ll(xy):
    lon, lat = to_ll(*xy)
    return round(lon, 6), round(lat, 6)


def ll_geom(g, tol=0.0):
    g = g.simplify(tol) if tol else g
    return mapping(transform(lambda x, y, z=None: to_ll(x, y), g))


def probs(cause, p, rng):
    rest = [c for c in CAUSES if c != cause]
    top = int(round(p * 1000))
    w = np.floor(rng.dirichlet(np.ones(len(rest))) * (1000 - top)).astype(int)
    w[0] += 1000 - top - w.sum()
    return {cause: top / 1000, **{c: int(x) / 1000 for c, x in zip(rest, w)}}


def ev(feature, dim, text, value=None, limit=None, unit=None):
    return dict(feature=feature, dimension=dim, text=text, value=value, limit=limit, unit=unit)


# --- scenes ------------------------------------------------------------------------------
# An effect gets (track, t, truth_xy, speed) and returns None or a dict that overrides the normal
# scores and/or the reported position. Times are absolute UNIX seconds.

class Scene:
    def __init__(self, ap, sid, t0, seed, night=False, fog=False):
        self.ap, self.id, self.t0, self.night, self.fog = ap, sid, t0, night, fog
        self.tracks, self.rng = baseline(ap, t0, SCENE_S, seed=seed)
        self.effects, self.areas, self.events, self.focus = [], [], [], []
        self.on, self.off = t0 + ONSET, t0 + ONSET + 90
        perm = list(self.rng.permutation(len(self.tracks)))
        self.noise_ids = [self.tracks[i].track_id for i in perm[:2]]
        self.sparse_ids = [self.tracks[i].track_id for i in perm[2:4]]

    def add_vehicle(self, cls, line, speed, t_start=None):
        k = len(self.tracks)
        tr = Track(f"synthetic:veh_{300 + k:03d}:0", "vehicle", cls, None)
        t = tr.add_drive(self.t0 - 30 if t_start is None else t_start, line, speed)
        tr.add_still(t, self.t0 + SCENE_S + 60, line.coords[-1], course_at(line, line.length))
        if tr.segments[0].t0 > self.t0 - 60:
            tr.segments.insert(0, type(tr.segments[0])(self.t0 - 60, tr.segments[0].t0, None, line.coords[0], 0, 0, course_at(line, 0)))
        self.tracks.append(tr)
        return tr


def route_from(ap, node, length, kind="service_road", tries=40):
    """A route of about `length` metres starting at `node`."""
    for dest in sorted(ap.graphs[kind].nodes, key=lambda n: abs(Point(ap.xy[n]).distance(Point(ap.xy[node])) - length))[:tries]:
        line = ap.route(kind, node, dest)
        if line is not None and line.length > 0.6 * length:
            return line
    raise RuntimeError("no route")


def near_runway_node(ap, ref, frac, offset):
    """A service-road node about `offset` metres from a runway axis, near position `frac` along it."""
    ax = ap.runways[ref]["axis"]
    p = ax.interpolate(frac, normalized=True)
    return min(ap.graphs["service_road"].nodes,
               key=lambda n: abs(ax.distance(Point(ap.xy[n])) - offset) + 0.3 * Point(ap.xy[n]).distance(p))


def apron_with_masts(ap, cams, k=0):
    masts = [c for c in cams if c["kind"] == "mast" and c["status"] == "online"]
    big = [a for a in ap.aprons if a["poly"].area > 15000]
    return sorted(big, key=lambda a: min(Point(c["xy"]).distance(a["poly"].centroid) for c in masts))[k]


def area_effect(s, area_id, label, poly_fn, cause="possible_interference", jitter=18, integ=(18, 32), conf=(.52, .66),
                action="area_gnss_unreliable", action_text=None):
    """Every track inside the (possibly moving) area degrades together and joins one area alert."""
    s.areas.append(dict(id=area_id, label=label, poly_fn=poly_fn, action=action, action_text=action_text))

    def eff(track, t, xy, v):
        poly = poly_fn(t)
        if poly is None or not poly.contains(Point(xy)):
            return None
        gap = int(s.rng.integers(11, 18))
        return dict(reported=(xy[0] + s.rng.normal(0, jitter), xy[1] + s.rng.normal(0, jitter)), integ=s.rng.uniform(*integ),
                    norm=s.rng.uniform(80, 92), cause=cause, p=s.rng.uniform(.5, .62), conf=s.rng.uniform(*conf), area=area_id,
                    action=action, action_text=action_text,
                    dims=dict(kinetic=s.rng.uniform(35, 55), temporal=s.rng.uniform(30, 45), spatial=s.rng.uniform(80, 92), contextual=s.rng.uniform(85, 95)),
                    evidence=[ev("flt_deg_rate_loo", "fleet", f"{s.rng.integers(70, 95)}% of other assets in this area are degraded at the same time", .8, None, "ratio"),
                              ev("tmp_gap_max_s", "temporal", f"No position for {gap} s", gap, 10, "s")])
    s.effects.append(eff)


def scenario_normal(ap, cams):
    s = Scene(ap, "normal_ops", DAY, seed=20)
    s.on = s.off = s.t0 + SCENE_S + 1
    return s, dict(title="Normal operations", category="Baseline",
                   story="A normal afternoon: aircraft taxiing, service vehicles at the stands. Everything trusted.")


def scenario_phantom(ap, cams):
    s = Scene(ap, "phantom_incursion", DAY + 600, seed=21)
    r = ap.runways["16R/34L"]
    line = route_from(ap, near_runway_node(ap, "16R/34L", 0.55, 280), 900)
    tr = s.add_vehicle("baggage_tractor", line, 5.5, t_start=s.t0 - 20)
    s.focus = [tr.track_id]
    s.events.append(dict(event_id="ev_phantom", kind="phantom_incursion", title="Phantom runway incursion",
                         t_start=s.on, t_end=s.off, track_ids=[tr.track_id]))

    def eff(track, t, xy, v):
        if track is not tr or not (s.on <= t <= s.off):
            return None
        q = r["axis"].interpolate(r["axis"].project(Point(xy)))
        jump = Point(xy).distance(q)
        return dict(reported=(q.x + s.rng.normal(0, 4), q.y + s.rng.normal(0, 4)), integ=s.rng.uniform(18, 30), norm=s.rng.uniform(20, 32),
                    cause="technical_error", p=s.rng.uniform(.62, .72), conf=s.rng.uniform(.78, .86), action="verify_radio",
                    action_text="Verify the vehicle's position by radio before holding the runway.",
                    dims=dict(kinetic=s.rng.uniform(5, 15), temporal=s.rng.uniform(80, 92), spatial=s.rng.uniform(25, 35), contextual=s.rng.uniform(8, 18)),
                    evidence=[ev("kin_speed_resid_max", "kinetic", f"Position jumped {jump:.0f} m in 5 s but the vehicle reports {v * 3.6:.0f} km/h", jump / 5, 10, "m/s"),
                              ev("ctx_type_violation_crit_max", "contextual", "A baggage tractor is not authorized on Runway 16R/34L", 1, 0, "0-1")])
    s.effects.append(eff)
    return s, dict(title="Phantom runway incursion", category="Data fault",
                   story="A tractor's GPS suddenly puts it on Runway 16R/34L. A runway camera sees an empty runway: the position is wrong, not the tractor.")


def scenario_real(ap, cams):
    s = Scene(ap, "real_incursion", DAY + 1500, seed=22)
    r = ap.runways["16L/34R"]
    gate = near_runway_node(ap, "16L/34R", 0.3, 160)
    lengths = nx.single_source_dijkstra_path_length(ap.graphs["service_road"], gate, weight="w")
    far = min(lengths, key=lambda n: abs(lengths[n] - 700))
    approach = ap.route("service_road", far, gate)
    on = r["axis"].interpolate(r["axis"].project(Point(ap.xy[gate])))
    along = r["axis"].interpolate(r["axis"].project(on) + 260)
    excursion = LineString([ap.xy[gate], (on.x, on.y), (along.x, along.y), ap.xy[gate]])
    tr = Track("synthetic:veh_290:0", "vehicle", "fuel_truck", None)
    t = s.on - 6 - approach.length / 7.0 - Point(ap.xy[gate]).distance(on) / 6.0
    tr.add_still(s.t0 - 60, t, approach.coords[0], course_at(approach, 0))
    t = tr.add_drive(t, approach, 7.0)
    t = tr.add_drive(t, excursion, 6.0)
    tr.add_still(t, s.t0 + SCENE_S + 60, excursion.coords[-1], 0)
    s.tracks.append(tr)
    s.focus = [tr.track_id]
    s.events.append(dict(event_id="ev_real", kind="real_incursion", title="Real runway incursion",
                         t_start=s.on, t_end=s.off, track_ids=[tr.track_id]))
    dist = r["axis"].distance(Point(ap.xy[gate]))

    def eff(track, t, xy, v):
        if track is not tr or not r["poly"].buffer(20).contains(Point(xy)):
            return None
        return dict(integ=s.rng.uniform(88, 96), norm=s.rng.uniform(12, 25), cause="behavioral_anomaly", p=s.rng.uniform(.8, .9),
                    conf=s.rng.uniform(.86, .93), action="act_now", action_text="Act now: position data is sound and the vehicle is on the runway.",
                    dims=dict(kinetic=s.rng.uniform(88, 98), temporal=s.rng.uniform(90, 99), spatial=s.rng.uniform(15, 25), contextual=s.rng.uniform(5, 12)),
                    evidence=[ev("ctx_type_violation_crit_max", "contextual", "A fuel truck is not authorized on Runway 16L/34R", 1, 0, "0-1"),
                              ev("spa_route_dist_max_m", "spatial", f"{dist:.0f} m from the nearest authorized route", dist, 25, "m")])
    s.effects.append(eff)
    return s, dict(title="Real runway incursion", category="Real event",
                   story="A fuel truck really drives onto Runway 16L/34R. The data is sound, so the alert says act now, and a runway camera confirms it.")


def loop_vehicles(s, apron, classes, speed=4.0, first_id=280):
    inner = apron["poly"].buffer(-10)
    inner = inner if inner.geom_type == "Polygon" else max(inner.geoms, key=lambda g: g.area)
    ring = list(inner.exterior.coords)
    loop = LineString(ring * 6)
    out = []
    for k, cls in enumerate(classes):
        tr = Track(f"synthetic:veh_{first_id + k:03d}:0", "vehicle", cls, None)
        tr.add_drive(s.t0 - 60 - k / len(classes) * LineString(ring).length / speed, loop, speed)
        s.tracks.append(tr)
        out.append(tr.track_id)
    return out


def scenario_sector(ap, cams):
    s = Scene(ap, "sector_interference", DAY + 2400, seed=23)
    apron = apron_with_masts(ap, cams)
    c = apron["poly"].centroid
    name = ap.apron_name((c.x, c.y))
    sector = apron["poly"].buffer(70).simplify(5)
    members = loop_vehicles(s, apron, ["bus", "baggage_tractor", "baggage_tractor", "catering_truck", "fuel_truck"])
    s.off = s.on + 120
    area_effect(s, "area_0001", f"Possible interference: apron near {name}", lambda t: sector if s.on <= t <= s.off else None,
                action_text=f"GNSS is unreliable on the apron near {name}: confirm positions visually.")
    s.focus = members
    s.events.append(dict(event_id="ev_sector", kind="sector_interference", title="Sector interference",
                         t_start=s.on, t_end=s.off, track_ids=members[:3]))
    return s, dict(title="Apron interference", category="Possible interference",
                   story=f"Five vehicles on the apron near {name} lose GNSS at the same moment. One area alert instead of five, and a mast camera shows the vehicles are where they should be.")


def scenario_jammer(ap, cams):
    s = Scene(ap, "jammer_car", DAY + 3300, seed=24)
    apron = apron_with_masts(ap, cams, 1)
    c = apron["poly"].centroid
    path = None
    for dx, dy in ((-700, 350), (-500, -500), (600, 400), (0, 700)):
        a = ap.nearest("service_road", (c.x + dx, c.y + dy))
        b = ap.nearest("service_road", (c.x - dx, c.y - dy))
        path = ap.route("service_road", a, b)
        if path is not None and path.length > 900:
            break
    if path.length > 1250:
        path = substring(path, (path.length - 1200) / 2, (path.length + 1200) / 2)
    s.off = s.on + 130
    speed = path.length / (s.off - s.on)

    def jam_xy(t):
        if not (s.on <= t <= s.off):
            return None
        p = path.interpolate((t - s.on) * speed)
        return (p.x, p.y)

    def poly(t):
        xy = jam_xy(t)
        return Point(xy).buffer(240, quad_segs=10) if xy else None

    # vehicles parked or loading along the road the jammer drives down
    kinds = ["baggage_tractor", "bus", "catering_truck", "baggage_tractor", "fuel_truck", "baggage_tractor", "bus", "baggage_tractor", "catering_truck", "fuel_truck"]
    for k in range(int(path.length // 120) + 1):
        cls, f = kinds[k % len(kinds)], min(0.98, (40 + 120 * k) / path.length)
        p, q = path.interpolate(f, normalized=True), path.interpolate(min(f + 0.02, 1), normalized=True)
        side = 18 if k % 2 else -18
        dx, dy = q.x - p.x, q.y - p.y
        nrm = math.hypot(dx, dy) or 1
        tr = Track(f"synthetic:veh_{400 + k:03d}:0", "vehicle", cls, None)
        tr.add_still(s.t0 - 60, s.t0 + SCENE_S + 60, (p.x - dy / nrm * side, p.y + dx / nrm * side), course_at(path, path.project(p)))
        s.tracks.append(tr)
    name = ap.apron_name((c.x, c.y))
    area_effect(s, "area_jam", f"Possible interference: moving source near {name}", poly,
                action_text="GNSS is unreliable inside the moving interference area: confirm positions visually and alert security.")
    return s, dict(title="Jammer in a passing car", category="Possible interference", jam=True,
                   story="A car with a cheap GPS jammer drives past the aprons. The degraded area moves with it, vehicles are warned before they enter, and security gets a place to look.")


def scenario_spoof(ap, cams):
    s = Scene(ap, "approach_spoofing", DAY + 4200, seed=25)
    used_hex, used_cs = set(), set()
    mid = ap.runways["07/25"]["axis"].interpolate(0.5, normalized=True)
    fake = (mid.x + 4200, mid.y + 5200)
    arrivals = [approach_track(ap, s.rng, used_hex, used_cs, ref, s.on + 110 + 70 * k)
                for k, ref in enumerate(["16L/34R", "16L/34R", "16R/34L"])]
    s.tracks += arrivals
    s.focus = [a.track_id for a in arrivals]
    s.off = s.on + 100

    def eff(track, t, xy, v):
        if track not in arrivals or not (s.on <= t <= s.off) or track.alt(t) is None:
            return None
        k = arrivals.index(track)
        ang = (t - s.on) / 40 + k * 2.1
        rep = (fake[0] + 350 * math.cos(ang), fake[1] + 350 * math.sin(ang))
        jump = Point(xy).distance(Point(rep))
        return dict(reported=rep, integ=s.rng.uniform(10, 24), norm=s.rng.uniform(18, 30), cause="possible_spoofing", p=s.rng.uniform(.66, .78),
                    conf=s.rng.uniform(.8, .9), action="verify_radio",
                    action_text="Cross-check with radar and the pilot: the reported position is not credible.",
                    dims=dict(kinetic=s.rng.uniform(4, 12), temporal=s.rng.uniform(70, 85), spatial=s.rng.uniform(10, 22), contextual=s.rng.uniform(15, 30)),
                    evidence=[ev("kin_speed_resid_max", "kinetic", f"Reported position is {jump / 1000:.1f} km from where speed and track put it", None, 10, "m/s"),
                              ev("flt_deg_rate_loo", "fleet", "Three arrivals report positions on the same small circle", 1, None, "ratio"),
                              ev("ctx_app_lateral_dev_deg", "contextual", "Off the approach path by more than 20°", 20, 3, "deg")])
    s.effects.append(eff)
    return s, dict(title="Approach spoofing", category="Possible spoofing",
                   story="Three arriving aircraft suddenly report positions on the same small circle far from the runway: the signature of GNSS spoofing seen over the Baltic and Eastern Mediterranean.")


def static_halo_bands(ap, terms=None):
    terms = terms or ap.terminals
    bands = []
    for inner, outer, level, err in ((0, 35, 0.55, 9.0), (35, 70, 0.35, 6.0), (70, 110, 0.18, 3.0)):
        ring = unary_union([t["poly"].buffer(outer) for t in terms])
        if inner:
            ring = ring.difference(unary_union([t["poly"].buffer(inner) for t in terms]))
        bands.append((ring.simplify(4), level, err))
    return bands


def scenario_multipath(ap, cams):
    s = Scene(ap, "multipath_terminal", DAY + 5100, seed=26)
    t3 = next(t for t in ap.terminals if "Terminal 3" in (t["name"] or ""))
    zone = t3["poly"].buffer(70)
    for k, cls in enumerate(["bus", "baggage_tractor", "catering_truck", "bus"]):
        c = t3["poly"].exterior.interpolate(k / 4 + 0.1, normalized=True)
        line = route_from(ap, ap.nearest("service_road", (c.x, c.y)), 450)
        s.add_vehicle(cls, LineString(list(line.coords)[::-1]), 5.0, t_start=s.on - 70 - 25 * k)
    s.off = s.t0 + SCENE_S

    def eff(track, t, xy, v):
        if t < s.on or track.domain != "vehicle" or not zone.contains(Point(xy)):
            return None
        return dict(reported=(xy[0] + s.rng.normal(0, 7), xy[1] + s.rng.normal(0, 7)), integ=s.rng.uniform(56, 66), norm=s.rng.uniform(85, 96),
                    cause="degraded", p=s.rng.uniform(.52, .64), conf=s.rng.uniform(.5, .66), action="monitor",
                    action_text="Keep watching: positions next to Terminal 3 are less accurate (signal reflections).",
                    dims=dict(kinetic=s.rng.uniform(55, 70), temporal=s.rng.uniform(85, 95), spatial=s.rng.uniform(80, 92), contextual=s.rng.uniform(90, 99)),
                    evidence=[ev("kin_pos_jitter_m", "kinetic", f"Position wanders {s.rng.uniform(6, 11):.0f} m while the vehicle drives straight", None, 3, "m"),
                              ev("spa_zone_crit_max", "spatial", "Inside the signal shadow of Terminal 3")])
    s.effects.append(eff)
    s.static_terms = [t3]
    return s, dict(title="Multipath near the terminal", category="Degraded data",
                   story="Next to Terminal 3 the satellite signals bounce off the facade. Vehicles there get less accurate positions: the system lowers trust without raising a false alarm.")


def scenario_frozen(ap, cams):
    s = Scene(ap, "frozen_receiver", NIGHT + 600, seed=27, night=True)
    gate = [c for c in cams if c["kind"] == "stand" and c["status"] == "online"][0]
    cx, cy = gate["xy"]
    hx, hy = math.sin(math.radians(gate["heading_deg"])), math.cos(math.radians(gate["heading_deg"]))
    target = (cx + hx * 70, cy + hy * 70)  # in front of a gate camera without infrared
    node = ap.nearest("service_road", target)
    tr = s.add_vehicle("bus", route_from(ap, node, 900), 8.3, t_start=s.on - 1)
    s.focus = [tr.track_id]
    frozen = {}

    def eff(track, t, xy, v):
        if track is not tr or t < s.on:
            return None
        frozen.setdefault("xy", xy)
        dt = t - s.on
        if dt < 10:
            return dict(reported=frozen["xy"])
        return dict(reported=frozen["xy"], integ=s.rng.uniform(22, 34), norm=s.rng.uniform(78, 90), cause="technical_error", p=s.rng.uniform(.64, .76),
                    conf=s.rng.uniform(.7, .82), action="verify_visual", reported_speed=v,
                    action_text=f"Confirm the bus position visually: its position has not changed for {dt:.0f} s while it reports {v * 3.6:.0f} km/h.",
                    dims=dict(kinetic=s.rng.uniform(10, 20), temporal=s.rng.uniform(5, 15), spatial=s.rng.uniform(80, 90), contextual=s.rng.uniform(85, 95)),
                    evidence=[ev("tmp_frozen_run_s", "temporal", f"Same position for {dt:.0f} s", dt, 10, "s"),
                              ev("kin_speed_resid_max", "kinetic", f"Reports {v * 3.6:.0f} km/h but does not move", v, 1, "m/s")])
    s.effects.append(eff)
    return s, dict(title="Frozen receiver at night", category="Technical error", night=True,
                   story="At night a bus's receiver freezes: same position, but still reporting 30 km/h. The nearest gate camera has no infrared, so the system says plainly that it can't confirm.")


def scenario_space_weather(ap, cams):
    s = Scene(ap, "space_weather", DAY - 4 * 3600, seed=28, fog=True)
    s.off = s.t0 + SCENE_S
    whole = unary_union([r["poly"] for r in ap.runways.values()] + [a["poly"] for a in ap.aprons]).convex_hull.buffer(300)
    area_effect(s, "area_wx", "Reduced GNSS accuracy, airport-wide (no local source)", lambda t: whole if t >= s.on else None,
                cause="gnss_anomaly", jitter=4, integ=(52, 66), conf=(.3, .5), action="monitor",
                action_text="Keep watching: GNSS accuracy is reduced across the airport. Keep extra separation; no local source found.")
    return s, dict(title="Space weather in fog", category="GNSS anomaly", fog=True,
                   story="A burst of solar activity lowers GNSS accuracy everywhere at once, with no single source. In the morning fog the cameras can't help either.")


def scenario_speeding(ap, cams):
    s = Scene(ap, "speeding_apron", DAY + 6000, seed=29)
    apron = apron_with_masts(ap, cams, 0)
    inner = apron["poly"].buffer(-15)
    inner = inner if inner.geom_type == "Polygon" else max(inner.geoms, key=lambda g: g.area)
    ring = inner.exterior
    best = max(((ring.interpolate(i / 20, normalized=True), ring.interpolate((i / 20 + .5) % 1, normalized=True)) for i in range(20)),
               key=lambda ab: ab[0].distance(ab[1]))
    a, b = best
    tr = s.add_vehicle("catering_truck", LineString([a, b, a, b, a, b]), 15.3, t_start=s.on - 4)
    s.focus = [tr.track_id]

    def eff(track, t, xy, v):
        if track is not tr or v < 10:
            return None
        return dict(integ=s.rng.uniform(88, 97), norm=s.rng.uniform(22, 34), cause="behavioral_anomaly", p=s.rng.uniform(.78, .88), conf=s.rng.uniform(.85, .93),
                    action="act_now", action_text=f"Act now: contact the driver, {v * 3.6:.0f} km/h on the apron (limit 30 km/h).",
                    dims=dict(kinetic=s.rng.uniform(85, 95), temporal=s.rng.uniform(90, 99), spatial=s.rng.uniform(80, 92), contextual=s.rng.uniform(15, 28)),
                    evidence=[ev("ctx_zone_speed_ratio_max", "contextual", f"{v * 3.6:.0f} km/h in a 30 km/h apron zone", round(v * 3.6 / 30, 2), 1, "ratio")])
    s.effects.append(eff)
    return s, dict(title="Speeding on the apron", category="Real event",
                   story="A catering truck crosses the apron at 55 km/h. The position is trustworthy and the behaviour is wrong: a real event, confirmed by an apron camera.")


# --- verdict assembly ----------------------------------------------------------------------

def severity_level(score):
    return next((lvl for thr, lvl in P.SEVERITY_LEVELS if score >= thr), "none")


def conf_level(c):
    return "high" if c >= P.CONF_HIGH else "medium" if c >= P.CONF_MEDIUM else "low"


ACTION_DEFAULT = {"none": "No action.", "monitor": "Keep watching: position accuracy is reduced."}


def run_scene(s: Scene, cov: Coverage, outdir: Path):
    ap, rng = s.ap, s.rng
    smooth, trust, abn = {}, {}, {}
    times = [s.t0 + k * STEP for k in range(SCENE_S // STEP + 1)]
    bands = static_halo_bands(ap, getattr(s, "static_terms", None))
    static_frame = [dict(type="Feature", geometry=ll_geom(bands[0][0], 10),
                         properties=dict(risk_zone_id="static_terminals", kind="static", level=bands[0][1], label="Signal shadow: terminals",
                                         expected_error_m=bands[0][2]))]
    by_id = {tr.track_id: tr for tr in s.tracks}
    frames_out, cams_out = [], []
    for t in times:
        verdicts, checks, members = [], {}, {}
        for tr in s.tracks:
            if not tr.active(t):
                continue
            xy, course, speed = tr.state(t)
            alt = tr.alt(t)
            n = lambda lo, hi: float(rng.uniform(lo, hi))  # noqa: E731
            sc = dict(integ=n(90, 99), norm=n(88, 100), cause="plausible", p=n(.85, .95), conf=n(.82, .95), action="none", action_text=None,
                      dims=dict(kinetic=n(92, 100), temporal=n(90, 100), spatial=n(90, 100), contextual=n(92, 100)), evidence=[], area=None,
                      reported=(xy[0] + rng.normal(0, 1.2), xy[1] + rng.normal(0, 1.2)), reported_speed=speed)
            if tr.track_id in s.noise_ids and (t - s.t0 + 60) % 120 < 15:  # brief harmless dips: real data is never perfect
                sc.update(integ=n(62, 69), cause="degraded", p=n(.4, .5), conf=n(.5, .6), action="monitor")
            if tr.track_id in s.sparse_ids:
                sc.update(conf=n(.3, .42))
            for eff in s.effects:
                o = eff(tr, t, xy, speed)
                if o:
                    sc.update({k: v for k, v in o.items() if v is not None})
            integ_raw, norm = sc["integ"], sc["norm"]
            prev = smooth.get(tr.track_id, integ_raw)
            a = P.EMA_ALPHA_DOWN if integ_raw < prev else P.EMA_ALPHA_UP
            integ = a * integ_raw + (1 - a) * prev
            smooth[tr.track_id] = integ
            st = trust.get(tr.track_id, "trusted")
            if st == "untrusted":
                st = "untrusted" if integ <= P.UNTRUSTED_EXIT else ("caution" if integ < P.CAUTION_EXIT else "trusted")
            elif st == "caution":
                st = "untrusted" if integ < P.UNTRUSTED_ENTER else ("trusted" if integ > P.CAUTION_EXIT else "caution")
            else:
                st = "untrusted" if integ < P.UNTRUSTED_ENTER else ("caution" if integ < P.CAUTION_ENTER else "trusted")
            trust[tr.track_id] = st
            ab = abn.get(tr.track_id, False)
            ab = norm <= P.ABNORMAL_EXIT if ab else norm < P.ABNORMAL_ENTER
            abn[tr.track_id] = ab
            ns = "abnormal" if ab else "expected"
            cause = sc["cause"]
            if st == "trusted" and cause not in ("plausible", "behavioral_anomaly"):
                cause = "plausible"
            if st == "untrusted" and cause == "plausible":
                cause = "technical_error"
            rep = sc["reported"]
            zid, zname, crit = ap.zone_of(rep, tr.domain, airborne=alt is not None and alt > 5)
            score = round(min(1.0, max(1 - integ / 100, 1 - norm / 100) * crit), 3)
            action = sc["action"]
            if st == "trusted" and ns == "expected":
                action = "none"
            elif action == "none":
                action = "monitor"
            area = sc["area"] if st != "trusted" else None
            if area:
                members.setdefault(area, []).append(tr.track_id)
            text = sc["action_text"] if (action == sc["action"] and sc["action_text"]) else ACTION_DEFAULT.get(action, "Check this position.")
            lon, lat = ll(rep)
            verdicts.append(dict(
                track_id=tr.track_id, asset_id=tr.track_id.split(":")[1], domain=tr.domain, asset_class=tr.asset_class, callsign=tr.callsign,
                t=t, window_s=C.WINDOW_S,
                position=dict(lat=lat, lon=lon, alt_m=None if alt is None else round(alt), track_deg=round(course, 1),
                              speed_mps=round(sc["reported_speed"], 1)),
                integrity=round(integ, 1), integrity_raw=round(integ_raw, 1), normality=round(norm, 1),
                dimensions={k: round(min(100.0, max(0.0, v)), 1) for k, v in sc["dims"].items()},
                trust_state=st, normality_state=ns, quadrant=K.quadrant_of(st, ns),
                confidence=round(sc["conf"], 2), confidence_level=conf_level(sc["conf"]),
                cause=cause, cause_probs=probs(cause, sc["p"], rng),
                severity=dict(level=severity_level(score), score=score, zone_id=zid, zone_name=zname, zone_criticality=crit),
                evidence=sc["evidence"][:3] if (st != "trusted" or ns == "abnormal") else [],
                action=dict(code=action, text=text), area_alert_id=area, early_warning=None))
            if action != "none":
                prefer = "runway" if zid.startswith("rwy") else ("mast" if area else None)
                checks[tr.track_id] = cov.check(rep, xy, night=s.night, fog=s.fog, prefer=prefer, rng=rng)
        zones = list(static_frame)
        for ar in s.areas:
            poly = ar["poly_fn"](t)
            ids = members.get(ar["id"], [])
            if poly is None or len(ids) < 2:
                for v in verdicts:  # a lone track is not an area alert
                    if v["area_alert_id"] == ar["id"]:
                        v["area_alert_id"] = None
                continue
            zones.append(dict(type="Feature", geometry=ll_geom(poly, 3),
                              properties=dict(risk_zone_id=f"live_{ar['id']}", kind="live", level=0.85 if ar["action"] != "monitor" else 0.4,
                                              label=ar["label"], area_alert_id=ar["id"], track_ids=ids,
                                              action=dict(code=ar["action"], text=ar["action_text"] or ACTION_DEFAULT["monitor"]),
                                              t_start=s.on, t_end=s.off)))
            if ar["action"] == "monitor":
                continue
            for v in verdicts:  # early warning: trusted vehicles about to enter the area
                if v["area_alert_id"] or v["domain"] != "vehicle":
                    continue
                tr = by_id[v["track_id"]]
                xy, _, spd = tr.state(t)
                if spd < 2:
                    continue
                d = poly.exterior.distance(Point(xy))
                if not (20 < d < 320) or poly.contains(Point(xy)):
                    continue
                eta = round(d / spd)
                if eta > 60 or not poly.contains(Point(tr.state(t + eta + 5)[0])):
                    continue
                hit = poly.exterior.interpolate(poly.exterior.project(Point(xy)))
                v["early_warning"] = dict(risk_zone_id=f"live_{ar['id']}", eta_s=float(eta))
                zones.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=[list(ll(xy)), list(ll((hit.x, hit.y)))]),
                                  properties=dict(risk_zone_id=f"forecast_{v['asset_id']}", kind="forecast", level=0.85,
                                                  label=f"Enters the interference area in {eta:.0f} s", track_ids=[v["track_id"]],
                                                  enters_risk_zone_id=f"live_{ar['id']}", eta_s=float(eta), t_start=t, t_end=t + eta)))
        fr = K.ReplayFrame.model_validate(dict(t=t, verdicts=verdicts, risk_zones=dict(type="FeatureCollection", t=t, features=zones)))
        frames_out.append(fr.model_dump_json())
        cams_out.append(json.dumps(dict(t=t, checks=checks), separators=(",", ":")))
    man = K.ReplayManifest(airport="LIRF", t_start=times[0], t_end=times[-1], step_s=STEP, n_frames=len(times),
                           events=[K.ReplayEvent(**e) for e in s.events])
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "frames.jsonl").write_text("\n".join(frames_out) + "\n")
    (outdir / "cameras.jsonl").write_text("\n".join(cams_out) + "\n")
    (outdir / "manifest.json").write_text(man.model_dump_json(indent=2))
    (outdir / "static_halos.geojson").write_text(json.dumps(dict(type="FeatureCollection", simulated=True, features=[
        dict(type="Feature", geometry=ll_geom(g, 2), properties=dict(kind="static", level=lvl, expected_error_m=err, label="Signal shadow (buildings)"))
        for g, lvl, err in bands]), separators=(",", ":")))
    return outdir


SCENARIOS = [scenario_normal, scenario_phantom, scenario_real, scenario_sector, scenario_jammer, scenario_spoof,
             scenario_multipath, scenario_frozen, scenario_space_weather, scenario_speeding]

if __name__ == "__main__":
    ap = Airport()
    cams = build_cameras(ap)
    cov = Coverage(ap, cams)
    if OUT.exists():
        shutil.rmtree(OUT)
    index = []
    for build in SCENARIOS:
        s, meta = build(ap, cams)
        d = run_scene(s, cov, OUT / s.id)
        size = sum(f.stat().st_size for f in d.iterdir()) // 1024
        index.append(dict(id=s.id, dir=s.id, title=meta["title"], category=meta["category"], story=meta["story"],
                          t_start=s.t0, onset_t=s.on, focus=s.focus, night=s.night, fog=s.fog, jam=bool(meta.get("jam"))))
        print(f"{s.id:22} {len(s.tracks):3} tracks  {size:5} KB")
    (OUT / "index.json").write_text(json.dumps(dict(simulated=True, scenarios=index), indent=2))
    print(f"{len(index)} scenarios -> {OUT}")
