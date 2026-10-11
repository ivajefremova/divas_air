"""Per-sample precision and recall of the ADR detectors on generator events.

Only events with an ADR equivalent are scored, on vehicle tracks of ground
scenes (1-2 s cadence, the closest to ADR's 1 Hz). Truth is the generator's
per-point label; precision counts every flagged sample whose truth is not the
equivalent event as a false positive, whatever its cause.

    python -m divas_air.adr --synthetic-eval
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from divas_air import config
from divas_air.adr import behaviour, signal
from divas_air.adr import tunables as T
from divas_air.adr.kin import kinematics

POINTS = config.PROCESSED / "points" / "synthetic.parquet"
EVENTS = config.PROCESSED / "synth" / "events.parquet"
REPORT = config.PROCESSED / "adr" / "synthetic_eval.json"
COLUMNS = [
    "track_id", "asset_id", "seq", "t", "lat", "lon", "domain", "asset_class",
    "gs_mps", "heading_deg", "alt_geom_m", "typecode_raw",
    "label_cause", "label_event_id", "scene_id",
]  # fmt: skip

# ADR label -> generator (cause, mode); mode None = any mode of that cause
EQUIVALENT = {
    "position_jump": ("technical_error", "jump"),
    "frozen_position": ("technical_error", "freeze"),
    "fix_loss": ("technical_error", "loss"),
    "multipath_noise": ("degraded", None),
    "gnss_drift": ("gnss_anomaly", None),
    "zone_violation": (
        "behavioral_anomaly",
        "incursion",
    ),  # runway_incursion | unauthorized_zone
    "overspeed": ("behavioral_anomaly", "speeding"),
}


def _modes(events: pd.DataFrame) -> pd.Series:
    def mode(js):
        try:
            return json.loads(js).get("mode")
        except (TypeError, ValueError):
            return None

    return pd.Series(
        events["params_json"].map(mode).to_numpy(), index=events["event_id"]
    )


def pr(flag: np.ndarray, truth: np.ndarray) -> dict:
    tp = int((flag & truth).sum())
    return {
        "flagged": int(flag.sum()),
        "true": int(truth.sum()),
        "tp": tp,
        "precision": round(tp / flag.sum(), 4) if flag.sum() else None,
        "recall": round(tp / truth.sum(), 4) if truth.sum() else None,
    }


def evaluate(p: pd.DataFrame, modes: pd.Series, zones, groups: dict) -> dict:
    p = p.sort_values(["track_id", "t"], kind="stable").reset_index(drop=True)
    sig = signal.detect(p)
    seg = kinematics(p).seg
    # behaviour reads ADR class names: aircraft play aircraft_taxi, vehicles keep their category
    q = p.copy()
    q["typecode_raw"] = np.where(
        q["domain"] == "aircraft", "aircraft_taxi", q["asset_class"]
    )
    grp = q["asset_class"].map(groups).fillna("").to_numpy(dtype=object)
    beh = behaviour.detect(q, sig, zones, grp, seg, None)

    cause = p["label_cause"].astype("string").fillna("plausible").to_numpy(dtype=object)
    mode = p["label_event_id"].astype("string").map(modes).to_numpy(dtype=object)
    flags = {lab: sig[lab].to_numpy(bool) for lab in T.SIGNAL_LABELS}
    flags["zone_violation"] = beh["runway_incursion"].to_numpy(bool) | beh[
        "unauthorized_zone"
    ].to_numpy(bool)
    flags["overspeed"] = beh["overspeed"].to_numpy(bool)
    out = {"samples": len(p), "tracks": int(p["track_id"].nunique()), "labels": {}}
    for lab, (c, m) in EQUIVALENT.items():
        truth = (cause == c) & ((mode == m) if m else True)
        out["labels"][lab] = {
            "generator_event": f"{c}/{m or 'any'}",
            **pr(flags[lab], truth),
        }
    clean = cause == "plausible"
    out["false_flags_on_clean_samples"] = {
        lab: int((f & clean).sum()) for lab, f in flags.items()
    }
    out["clean_samples"] = int(clean.sum())
    # phantoms: zone labels raised on a wrong position and suppressed by a signal label
    unsound = (cause != "plausible") & (cause != "behavioral_anomaly")
    sup = {}
    for lab in ("runway_incursion", "unauthorized_zone"):
        raw = beh[f"raw_{lab}"].to_numpy(bool)
        fin = beh[lab].to_numpy(bool)
        sup[lab] = {
            "raw_on_unsound_samples": int((raw & unsound).sum()),
            "suppressed": int((raw & ~fin).sum()),
            "suppressed_on_unsound_samples": int((raw & ~fin & unsound).sum()),
            "suppressed_on_real_behaviour": int(
                (raw & ~fin & (cause == "behavioral_anomaly")).sum()
            ),
        }
    out["phantom_suppression"] = sup
    return out


def run() -> dict:
    from divas_air.geo.adr import category_groups, load_adr

    t0 = time.time()
    p = pd.read_parquet(
        POINTS,
        columns=COLUMNS,
        filters=[("domain", "==", "vehicle")],
    )
    p = p[p["scene_id"].astype(str).str.startswith("ground")]
    rep = evaluate(
        p, _modes(pd.read_parquet(EVENTS)), load_adr().zones, category_groups()
    )
    rep["runtime_s"] = round(time.time() - t0, 1)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=2))
    return rep
