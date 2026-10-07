import sys
import h3
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Polygon

# usage: python gpsjam_repro.py <tracks.parquet> <out_prefix> [h3_resolution]
src, out = sys.argv[1], sys.argv[2]
res = int(sys.argv[3]) if len(sys.argv) > 3 else 4
rule = sys.argv[4] if len(sys.argv) > 4 else "majority"
min_total = int(sys.argv[5]) if len(sys.argv) > 5 else 10

df = pd.read_parquet(src, columns=["icao24", "ts", "lat", "lon", "on_ground", "nac_p"])
df = df.sort_values(["icao24", "ts"])
df["nac_p"] = df.groupby("icao24").nac_p.ffill()        # NACp is only sent when it changes
df = df[df.nac_p.notna() & ~df.on_ground]

eligible = df.groupby("icao24").nac_p.max() >= 8        # reported good accuracy at least once
df = df[df.icao24.map(eligible)]

df["hex"] = [h3.latlng_to_cell(a, b, res) for a, b in zip(df.lat, df.lon)]
frac = df.assign(low=df.nac_p < 8).groupby(["hex", "icao24"]).low.mean()
per = (frac > 0 if rule == "any" else frac > 0.5).rename("bad").reset_index()
agg = per.groupby("hex").bad.agg(bad="sum", total="size").reset_index()
agg["percent_bad"] = 100 * (agg.bad - 1).clip(lower=0) / agg.total
agg = agg[agg.total >= min_total]
agg.to_parquet(f"{out}.parquet", index=False)

geom = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h)]) for h in agg.hex]
g = gpd.GeoDataFrame(agg, geometry=geom, crs="EPSG:4326")
color = pd.cut(g.percent_bad, [-1, 2, 10, 101], labels=["green", "gold", "red"]).astype(str)
ax = g.plot(color=color, edgecolor="white", linewidth=0.3, figsize=(8, 8))
ax.set_title(f"Reproduced GPSJam metric — {src.split('/')[-1]}")
plt.savefig(f"{out}.png", dpi=150, bbox_inches="tight")

print("hexagons:", len(agg),
      "| red (>10%):", (agg.percent_bad > 10).sum(),
      "| yellow (2-10%):", agg.percent_bad.between(2, 10, inclusive="right").sum())
print(agg.sort_values("percent_bad", ascending=False).head(10).to_string(index=False))