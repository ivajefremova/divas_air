import gzip, json, sys
from pathlib import Path
import pandas as pd

# usage: python filter_adsblol.py <day_folder> <out.parquet> [lat_min lon_min lat_max lon_max]
BOX = tuple(map(float, sys.argv[3:7])) if len(sys.argv) == 7 else (41.53, 11.89, 42.07, 12.61)
FT, KT = 0.3048, 0.514444

def load(p):
    raw = p.read_bytes()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    return json.loads(raw)

rows = []
for p in Path(sys.argv[1]).rglob("trace_full_*.json"):
    d = load(p)
    for pt in d["trace"]:
        lat, lon = pt[1], pt[2]
        if not (BOX[0] <= lat <= BOX[2] and BOX[1] <= lon <= BOX[3]):
            continue
        alt, det = pt[3], (pt[8] or {})
        rows.append({
            "icao24": d["icao"], "ts": d["timestamp"] + pt[0], "lat": lat, "lon": lon,
            "on_ground": alt == "ground",
            "alt_m": None if alt in ("ground", None) else alt * FT,
            "speed_mps": None if pt[4] is None else pt[4] * KT,
            "track_deg": pt[5],
            "vrate_mps": None if pt[7] is None else pt[7] * FT / 60,
            "nic": det.get("nic"), "nac_p": det.get("nac_p"), "sil": det.get("sil"),
            "callsign": det.get("flight"), "type": d.get("t"),
        })
pd.DataFrame(rows).to_parquet(sys.argv[2], index=False)
print(len(rows), "points written to", sys.argv[2])
