import glob
import numpy as np
import pandas as pd

env = pd.read_csv("data/reference/envelopes.csv").set_index("category")
types = pd.read_csv("data/reference/aircraft_types.csv").set_index("typecode").size_class

df = pd.concat(pd.read_parquet(f) for f in glob.glob("data/processed/adsblol_fco_*.parquet"))
ov = pd.read_csv("data/reference/type_overrides.csv", dtype=str).set_index("icao24").typecode
df["type"] = df.icao24.map(ov).fillna(df.type)
df = df.sort_values(["icao24", "ts"])
df["cls"] = df.type.map(types).fillna("other")

BASE_S = 5.0

def lagged_rates(sub):
    t = sub.ts.to_numpy(dtype=float)
    trk = sub.track_deg.to_numpy(dtype=float)
    spd = sub.speed_mps.to_numpy(dtype=float)
    j = np.searchsorted(t, t - BASE_S, side="right") - 1   # last point >= 5 s back
    has_prev = j >= 0
    j = np.clip(j, 0, None)
    dt = t - t[j]
    ok = has_prev & (dt >= BASE_S) & (dt <= 3 * BASE_S)    # skip coverage gaps
    dtrk = (trk - trk[j] + 180) % 360 - 180
    with np.errstate(invalid="ignore", divide="ignore"):
        turn = np.where(ok, np.abs(dtrk) / dt, np.nan)
        acc = np.where(ok, np.abs(spd - spd[j]) / dt, np.nan)
    return pd.DataFrame({"turn_dps": turn, "accel": acc}, index=sub.index)

rates = df.groupby("icao24", group_keys=False).apply(lagged_rates, include_groups=False)
df[["turn_dps", "accel"]] = rates
df["vrate_abs"] = df.vrate_mps.abs()

MARGIN = 1.5
checks = {"speed_mps": "max_air_speed_mps", "turn_dps": "max_turn_rate_dps",
          "accel": "max_accel_mps2", "vrate_abs": "max_vrate_mps"}

for cls, sub in df[~df.on_ground].groupby("cls"):
    if not env.loc[cls, "kinematic_checks"]:
        continue
    print(f"\n{cls} ({sub.icao24.nunique()} aircraft)")
    for col, lim_col in checks.items():
        lim = env.loc[cls, lim_col] * MARGIN
        v = sub[col].dropna()
        print(f"  {col:10s} p99.9={v.quantile(0.999):7.1f}  limit={lim:6.1f}  "
              f"over={np.mean(v > lim) * 100:.3f}%")