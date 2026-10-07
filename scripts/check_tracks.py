import sys
import pandas as pd

df = pd.read_parquet(sys.argv[1]).sort_values(["icao24", "ts"])
print(f"{len(df)} points, {df.icao24.nunique()} aircraft")

dt = df.groupby("icao24")["ts"].diff().dropna()
print("seconds between points: median", round(dt.median(), 1), "| 90th pct", round(dt.quantile(0.9), 1))

ap = df.lat.between(41.77, 41.86) & df.lon.between(12.20, 12.30)
g = df[ap & df.on_ground]
print(f"ground points at FCO: {len(g)} from {g.icao24.nunique()} aircraft")
if len(g):
    print("ground: median seconds between points", round(g.groupby("icao24")["ts"].diff().median(), 1))

print("nac_p present on", round(df.nac_p.notna().mean() * 100, 1), "% of points (sparse is normal, forward-fill later)")
print("file size MB:", round(df.memory_usage(deep=True).sum() / 1e6, 1))