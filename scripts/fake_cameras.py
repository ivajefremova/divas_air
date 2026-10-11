"""Simulated partner cameras: registry, coverage and camera checks.

SIMULATED. No real camera positions are known. Cameras are placed where such cameras usually are:
one per gate looking at its stand (partner turnaround cameras), masts over the aprons, and airport
CCTV along the runways. A ground point is covered by a camera when it is within range, inside the
field-of-view wedge, and the line of sight does not cross a building. Reliability drops with
distance, at night (unless the camera has infrared), in fog, and is zero when a camera is offline;
below RELIABLE the camera reports "cannot confirm" instead of a result.

    python scripts/fake_cameras.py      -> app/web/data/cameras.geojson
"""

import json
import math
import sys
from pathlib import Path

from shapely import STRtree
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_traffic import Airport, to_ll  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "app" / "web" / "data" / "cameras.geojson"
RELIABLE = 0.45          # below this the camera cannot confirm
SAME_SPOT_M = 50         # an object within this distance of the target counts as "at the spot"


def bearing(a, b):
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def build_cameras(ap: Airport):
    cams = []

    def add(kind, xy, heading, **kw):
        n = len(cams) + 1
        base = dict(stand=dict(height_m=12, fov_deg=75, range_m=140, provider="Partner (simulated)", infrared=False),
                    mast=dict(height_m=25, fov_deg=115, range_m=480, provider="Partner (simulated)", infrared=True),
                    runway=dict(height_m=18, fov_deg=55, range_m=1500, provider="Airport CCTV (simulated)", infrared=True))[kind]
        cams.append(dict(camera_id=f"CAM-{n:02d}", kind=kind, xy=xy, heading_deg=round(heading % 360, 1),
                         status="online", simulated=True, **{**base, **kw}))

    # gate cameras: on the terminal facade, looking at the stand
    stands = sorted(ap.stands, key=lambda s: s["ref"])
    for st in stands[::2][:26]:
        term = min(ap.terminals, key=lambda t: t["poly"].distance(Point(st["xy"])))
        edge = term["poly"].exterior.interpolate(term["poly"].exterior.project(Point(st["xy"])))
        d = Point(st["xy"]).distance(edge)
        if d > 260:
            continue
        mount = (edge.x + (st["xy"][0] - edge.x) * 6 / max(d, 1), edge.y + (st["xy"][1] - edge.y) * 6 / max(d, 1))
        add("stand", mount, bearing(mount, st["xy"]), label=f"Stand {st['ref']} ({term['name']})")
    # apron masts: at the edge of the larger aprons, looking across them
    for a in sorted(ap.aprons, key=lambda a: -a["poly"].area)[:11]:
        c = a["poly"].centroid
        edge = a["poly"].exterior.interpolate(a["poly"].exterior.project(Point(c.x + 400, c.y - 400)))
        add("mast", (edge.x, edge.y), bearing((edge.x, edge.y), (c.x, c.y)),
            label=f"Apron mast near {ap.apron_name((c.x, c.y))}", infrared=len(cams) % 2 == 0)
    # runway CCTV: beside each runway, one camera looking along each half
    for ref, r in ap.runways.items():
        ax = r["axis"]
        for frac, look in ((0.12, 0.35), (0.88, 0.62)):  # near each end, looking at the middle section
            p = ax.interpolate(frac, normalized=True)
            q = ax.interpolate(look, normalized=True)
            nx, ny = (ax.coords[-1][1] - ax.coords[0][1]), -(ax.coords[-1][0] - ax.coords[0][0])
            n = math.hypot(nx, ny)
            mount = (p.x + nx / n * 140, p.y + ny / n * 140)
            add("runway", mount, bearing(mount, (q.x, q.y)), label=f"Runway {ref} {'south' if frac < .5 else 'north'} end, looking inward")
    cams[len(cams) // 3]["status"] = "offline"  # a realistic gap: one camera down for maintenance
    return cams


class Coverage:
    def __init__(self, ap: Airport, cams):
        self.cams = cams
        self.blocks = [b["poly"] for b in ap.buildings if b["poly"].area > 150]
        self.tree = STRtree(self.blocks)

    def sees(self, cam, xy):
        d = math.dist(cam["xy"], xy)
        if d > cam["range_m"] or d < 3:
            return False, d
        off = abs((bearing(cam["xy"], xy) - cam["heading_deg"] + 180) % 360 - 180)
        if off > cam["fov_deg"] / 2:
            return False, d
        start = LineString([cam["xy"], xy]).interpolate(min(15, d / 2))  # leave the mounting building
        ray = LineString([(start.x, start.y), xy])
        for i in self.tree.query(ray):
            if self.blocks[i].intersects(ray):
                return False, d
        return True, d

    def reliability(self, cam, d, night, fog):
        if cam["status"] != "online":
            return 0.0, "camera offline"
        r = 0.97 * (1 - 0.55 * d / cam["range_m"])
        why = None
        if night and not cam["infrared"]:
            r *= 0.35
            why = "too dark, no infrared"
        if fog:
            r *= 0.4
            why = "fog"
        if r < RELIABLE and why is None:
            why = "too far"
        return r, why

    def check(self, target_xy, truth_xy, night=False, fog=False, prefer=None, rng=None):
        """Camera evidence for one alert. Looks at the reported spot, and at the true position when it differs."""
        results = []
        moved = math.dist(target_xy, truth_xy) > SAME_SPOT_M
        for cam in self.cams:
            for target, xy in (("reported", target_xy),) + ((("true", truth_xy),) if moved else ()):
                ok, d = self.sees(cam, xy)
                if not ok:
                    continue
                r, why = self.reliability(cam, d, night, fog)
                if r < RELIABLE:
                    outcome = "cannot_confirm"
                elif target == "reported":
                    outcome = "no_vehicle" if moved else "vehicle_seen"
                else:
                    outcome = "vehicle_seen"
                conf = max(0.05, min(0.99, r + (rng.normal(0, 0.02) if rng is not None else 0)))
                rank = r + (0.15 if prefer and cam["kind"] == prefer else 0) + (0.1 if night and cam["infrared"] else 0)
                results.append(dict(camera_id=cam["camera_id"], target=target, outcome=outcome, at=[round(v, 6) for v in to_ll(*xy)],
                                    confidence=round(conf, 2), distance_m=round(d), reason=why if outcome == "cannot_confirm" else None,
                                    _rank=rank))
        results.sort(key=lambda x: (x["outcome"] == "cannot_confirm", -x["_rank"]))
        for x in results:
            x.pop("_rank")
        if not results:
            summary = "not_covered"
        elif all(x["outcome"] == "cannot_confirm" for x in results):
            summary = "cannot_confirm"
        elif any(x["outcome"] == "no_vehicle" for x in results) or any(x["target"] == "true" and x["outcome"] == "vehicle_seen" for x in results):
            summary = "position_wrong"
        else:
            summary = "seen_at_position"
        return dict(summary=summary, results=results[:4])


def cameras_geojson(cams):
    feats = []
    for c in cams:
        lon, lat = to_ll(*c["xy"])
        props = {k: v for k, v in c.items() if k != "xy"}
        feats.append(dict(type="Feature", properties=props, geometry=dict(type="Point", coordinates=[round(lon, 6), round(lat, 6)])))
    return dict(type="FeatureCollection", name="cameras_simulated", features=feats)


if __name__ == "__main__":
    ap = Airport()
    cams = build_cameras(ap)
    OUT.write_text(json.dumps(cameras_geojson(cams)))
    print(f"{len(cams)} simulated cameras -> {OUT}  ({sum(c['kind']=='stand' for c in cams)} gate, "
          f"{sum(c['kind']=='mast' for c in cams)} mast, {sum(c['kind']=='runway' for c in cams)} runway; "
          f"{sum(c['status']!='online' for c in cams)} offline)")
