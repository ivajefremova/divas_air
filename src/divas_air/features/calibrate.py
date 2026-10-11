"""Dimension thresholds (specs/03_features.md requirement 8).

tau = max(registry default, 99.9th percentile over clean windows) for every
`calibrated` feature, separately per domain. Clean aircraft windows are `fco`
windows from non-held-out days; clean vehicle windows are synthetic windows
with label_frac == 0, from train scenes once module 4 has written the splits.
Envelope and fixed features keep their registry values.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from divas_air import config, params, registry

THRESHOLDS_PATH = config.REFERENCE / "dimension_thresholds.csv"
SPLITS_PATH = config.ROOT / "artifacts" / "models" / "splits.json"
DOMAINS = ("aircraft", "vehicle")


def features_path(source: str):
    return config.PROCESSED / "features" / f"{source}.parquet"


def not_held_out(t: np.ndarray) -> np.ndarray:
    """False on the last REAL_HOLDOUT_DAYS UTC days present in `t`."""
    day = np.floor(np.asarray(t, dtype="float64") / 86400.0)
    return day <= day.max() - params.REAL_HOLDOUT_DAYS


def train_scenes() -> set[str] | None:
    """Train scene ids from module 4's splits.json, or None if it does not exist yet."""
    if not SPLITS_PATH.exists():
        return None
    s = json.loads(SPLITS_PATH.read_text())
    if isinstance(s.get("train"), list):
        return set(map(str, s["train"]))
    for key in ("scenes", "scene_split", "splits"):
        m = s.get(key)
        if isinstance(m, dict):
            return {str(k) for k, v in m.items() if v == "train"}
    raise ValueError(f"unrecognized splits format in {SPLITS_PATH}")


def clean_windows() -> dict[str, tuple[pd.DataFrame, str]]:
    """Clean windows per domain, with a description of where they come from."""
    cols = registry.FEATURE_COLUMNS
    out: dict[str, tuple[pd.DataFrame, str]] = {}
    fco = features_path("fco")
    if fco.exists():
        f = pd.read_parquet(fco, columns=["t_end", "aux_domain", *cols])
        keep = (
            not_held_out(f["t_end"].to_numpy())
            & (f["aux_domain"] == "aircraft").to_numpy()
        )
        keep &= f["tmp_n_points"].to_numpy() >= params.MIN_POINTS
        # windows without any NACp are MLAT/TIS-B positions, not GNSS: not fitted on
        keep &= f["sig_nacp_median"].notna().to_numpy()
        days = pd.to_datetime(f.loc[keep, "t_end"], unit="s").dt.date
        out["aircraft"] = (
            f[keep],
            f"fco non-held-out {days.min()}..{days.max()}, with NACp",
        )
    syn = features_path("synthetic")
    if syn.exists():
        f = pd.read_parquet(
            syn, columns=["aux_domain", "label_frac", "scene_id", *cols]
        )
        keep = (
            (f["aux_domain"] == "vehicle")
            & (f["label_frac"] == 0)
            & (f["tmp_n_points"] >= params.MIN_POINTS)
        )
        scenes = train_scenes()
        if scenes is not None:
            keep &= f["scene_id"].isin(scenes)
        where = "synthetic clean vehicle windows" + (
            ", train scenes" if scenes is not None else ", all scenes"
        )
        out["vehicle"] = (f[keep.to_numpy()], where)
    return out


def fit_thresholds(
    clean: dict[str, tuple[pd.DataFrame, str]] | None = None,
) -> pd.DataFrame:
    clean = clean_windows() if clean is None else clean
    rows = []
    for s in registry.REGISTRY.values():
        if not s.scored:
            continue
        for domain in DOMAINS:
            tau, n, fitted_on = float(s.tau), 0, f"registry ({s.tau_source})"
            if s.tau_source == "calibrated":
                fitted_on = (
                    f"registry default (< {params.THRESHOLD_MIN_N} clean windows)"
                )
                if domain in clean:
                    df, where = clean[domain]
                    v = df[s.name].dropna().to_numpy(dtype="float64")
                    if len(v) >= params.THRESHOLD_MIN_N:
                        tau = max(
                            float(s.tau),
                            float(np.quantile(v, params.THRESHOLD_QUANTILE)),
                        )
                        n, fitted_on = len(v), where
            rows.append((s.name, domain, tau, float(s.scale), n, fitted_on))
    return pd.DataFrame(
        rows, columns=["name", "domain", "tau", "scale", "n", "fitted_on"]
    )


def calibrate() -> pd.DataFrame:
    th = fit_thresholds()
    th.to_csv(THRESHOLDS_PATH, index=False, float_format="%.6g")
    return th
