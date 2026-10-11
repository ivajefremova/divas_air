"""ADR per-sample result: trust, signal and behaviour labels, cause, evidence.

    python -m divas_air.adr

writes data/processed/adr/asset_tracks_scored.{parquet,csv} (one row per ADR
sample, ADR's row order, no positions) and asset_tracks_scored_report.json.
data/processed/adr/ is gitignored: ADR forbids redistribution.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from divas_air import config, schema
from divas_air.adr import behaviour, signal
from divas_air.adr import tunables as T
from divas_air.adr.kin import kinematics

OUT_DIR = config.PROCESSED / "adr"
POINTS_PATH = config.PROCESSED / "points" / "adr_mock.parquet"
ENGINE_VERDICTS = config.PROCESSED / "verdicts" / "adr_mock.parquet"
OWN_FEATURES = OUT_DIR / "adr_mock_features.parquet"
OWN_VERDICTS = OUT_DIR / "adr_mock_verdicts.parquet"
OUT_PARQUET = OUT_DIR / "asset_tracks_scored.parquet"
OUT_CSV = OUT_DIR / "asset_tracks_scored.csv"
REPORT_PATH = OUT_DIR / "asset_tracks_scored_report.json"
OUTPUT_COLUMNS = [
    "asset_id",
    "timestamp_unix",
    "trust",
    "signal_anomaly_label",
    "behaviour_anomaly_label",
    "cause",
    "evidence",
]


# --- trust ---------------------------------------------------------------------------


def engine_verdicts(points: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """The engine's verdict table for adr_mock: module 5's if it exists, else
    features with the ADR layer profile through the batch pipeline functions."""
    cols = ["track_id", "t_end", "integrity", "trust_state", "cause", "evidence_json"]
    if ENGINE_VERDICTS.exists():
        return pd.read_parquet(ENGINE_VERDICTS, columns=cols), str(ENGINE_VERDICTS)
    if not OWN_VERDICTS.exists():
        from divas_air import pipeline
        from divas_air.features import compute_features
        from divas_air.geo import MapLayers
        from divas_air.models import load_bundle

        f = compute_features(points, MapLayers.load(profile="adr"))
        f.to_parquet(OWN_FEATURES, index=False)
        v, _ = pipeline.verdicts(f, load_bundle(), pipeline.load_baseline())
        v.to_parquet(OWN_VERDICTS, index=False)
    return pd.read_parquet(OWN_VERDICTS, columns=cols), str(OWN_VERDICTS)


def sample_trust(p: pd.DataFrame, v: pd.DataFrame) -> pd.DataFrame:
    """Per sample, the verdict of the window ending at or just after it (same track);
    the track's last window for samples after it."""
    left = p[["track_id", "t"]].reset_index().sort_values("t", kind="stable")
    left["track_id"] = left["track_id"].astype(str)
    right = v.sort_values("t_end", kind="stable").copy()
    right["track_id"] = right["track_id"].astype(str)
    fwd = pd.merge_asof(
        left, right, left_on="t", right_on="t_end", by="track_id", direction="forward"
    )
    bwd = pd.merge_asof(
        left, right, left_on="t", right_on="t_end", by="track_id", direction="backward"
    )
    miss = fwd["t_end"].isna().to_numpy()
    out = fwd.copy()
    out.loc[miss, right.columns] = bwd.loc[miss, right.columns].to_numpy()
    return out.set_index("index").sort_index()


# --- cause and evidence --------------------------------------------------------------


def _first_text(evidence_json) -> str:
    try:
        ev = json.loads(evidence_json) if evidence_json else []
    except (TypeError, ValueError):
        ev = []
    return ev[0]["text"] if ev else "no evidence above its limit"


def _fmt(tpl: str, rows: pd.DataFrame) -> list[str]:
    return [tpl.format(**r) for r in rows.to_dict("records")]


def cause_and_evidence(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Signal label first, then behaviour, then the engine when it is not trusted."""
    n = len(df)
    cause = np.full(n, "plausible", dtype=object)
    text = np.full(n, "", dtype=object)
    sig, beh = (
        df["signal_anomaly_label"].to_numpy(),
        df["behaviour_anomaly_label"].to_numpy(),
    )
    eng = (sig == "") & (beh == "") & (df["trust_state"].to_numpy() != "trusted")
    eng_unsound = eng & np.isin(df["engine_cause"].to_numpy(), schema.UNSOUND_CAUSES)
    cause[eng_unsound] = df["engine_cause"].to_numpy()[eng_unsound]
    cause[beh != ""] = "behavioral_anomaly"
    for lab, c in T.CAUSE.items():
        cause[sig == lab] = c

    v = pd.DataFrame(
        {
            "trust": df["trust"],
            "frozen_s": df["frozen_s"],
            "moving_mps": df["moving_mps"],
            "step_m": df["step_m"],
            "gap_s": df["gap_s"],
            "scatter_m": df["scatter_m"],
            "speed_mps": np.fmax(df["gs_mps"], df["v5_mps"]),
            "bound_mps": df["bound_mps"],
            "asset_class": df["asset_class"],
            "heading_diff_deg": df["heading_diff_deg"],
            "alt_m": df["alt_geom_m"],
            "alt_dev_m": df["alt_dev_m"],
            "group": df["group"],
            "runway": df["runway"],
            "zone_class": df["zone_class"],
            "zone_id": df["zone_id"],
            "allowed": df["allowed"],
            "other_id": df["other_id"],
            "prox_m": df["prox_m"],
            "speed_kmh": df["v5_mps"] * 3.6,
            "limit_kmh": df["limit_mps"] * 3.6,
            "threshold_kmh": df["threshold_mps"] * 3.6,
            "stop_s": df["stop_s"],
            "stop_limit_s": df["stop_limit_s"],
        }
    )
    for lab in T.SIGNAL_LABELS:
        m = sig == lab
        if m.any() and lab in T.TEMPLATES:
            text[m] = _fmt(T.TEMPLATES[lab], v[m])
    for lab in T.BEHAVIOUR_LABELS:
        m = (beh == lab) & (sig == "")
        if m.any() and lab in T.TEMPLATES:
            text[m] = _fmt(T.TEMPLATES[lab], v[m])
    if eng.any():
        e = v.loc[eng, ["trust"]].copy()
        e["engine_text"] = [_first_text(x) for x in df.loc[eng, "engine_evidence"]]
        text[eng] = _fmt(T.TEMPLATES["engine"], e)
    clean = (sig == "") & (beh == "") & ~eng
    text[clean] = [T.TEMPLATES["clean"].format(trust=x) for x in df.loc[clean, "trust"]]
    return cause, text


# --- run -------------------------------------------------------------------------------


def score(
    points: pd.DataFrame,
    side: pd.DataFrame | None,
    verdicts: pd.DataFrame,
    zones,
    groups: pd.Series,
):
    """Full per-sample table (internal columns included), rows sorted by (track_id, t)."""
    p = points.sort_values(["track_id", "t"], kind="stable").reset_index(drop=True)
    rwy = None
    if side is not None:
        p = p.merge(
            side[
                ["track_id", "seq", "adr_row", "timestamp_unix", "runway_critical_ref"]
            ],
            on=["track_id", "seq"],
            how="left",
        )
        rwy = p["runway_critical_ref"]
    sig = signal.detect(p)
    seg = kinematics(p).seg
    grp = p["typecode_raw"].map(groups).fillna("").to_numpy(dtype=object)
    beh = behaviour.detect(p, sig, zones, grp, seg, rwy)
    tr = sample_trust(p, verdicts)
    df = pd.concat([p, sig, beh], axis=1)
    df["trust"] = tr["integrity"].to_numpy()
    df["trust_state"] = tr["trust_state"].to_numpy()
    df["engine_cause"] = tr["cause"].to_numpy()
    df["engine_evidence"] = tr["evidence_json"].to_numpy()
    df["signal_anomaly_label"] = df["signal_label"]
    df["behaviour_anomaly_label"] = df["behaviour_label"]
    df["cause"], df["evidence"] = cause_and_evidence(df)
    return df


def report(
    df: pd.DataFrame, verdicts: pd.DataFrame, manifest: dict, verdict_source: str
) -> dict:
    def per_label(col, labels, prefix=""):
        out = {}
        for lab in labels:
            m = df[prefix + lab].to_numpy(dtype=bool)
            out[lab] = {
                "samples": int(m.sum()),
                "tracks": int(df.loc[m, "track_id"].nunique()),
            }
        return out

    sig_any = df["signal_anomaly_label"] != ""
    agree = pd.crosstab(
        np.where(sig_any, "signal label", "no signal label"), df["trust_state"]
    )
    suppressed = {}
    for lab in (
        "runway_incursion",
        "unauthorized_zone",
        "aircraft_proximity",
        "overspeed",
        "unexpected_stop",
    ):
        m = df[f"raw_{lab}"] & ~df[lab]
        suppressed[lab] = {
            "samples": int(m.sum()),
            "tracks": int(df.loc[m, "track_id"].nunique()),
        }
    return {
        "dataset_version": manifest.get("versione"),
        "dataset": manifest.get("dataset"),
        "samples": len(df),
        "tracks": int(df["track_id"].nunique()),
        "verdicts_from": verdict_source,
        "window_trust_state_share": verdicts["trust_state"]
        .value_counts(normalize=True)
        .round(5)
        .to_dict(),
        "sample_trust_state_share": df["trust_state"]
        .value_counts(normalize=True)
        .round(5)
        .to_dict(),
        "signal_labels": per_label("signal", T.SIGNAL_LABELS),
        "behaviour_labels_raw": per_label("beh", T.BEHAVIOUR_LABELS, "raw_"),
        "behaviour_labels": per_label("beh", T.BEHAVIOUR_LABELS),
        "suppressed_by_signal": suppressed,
        "samples_with_signal_label": int(sig_any.sum()),
        "samples_with_behaviour_label": int(
            (df["behaviour_anomaly_label"] != "").sum()
        ),
        "detector_vs_engine_state": {r: agree.loc[r].to_dict() for r in agree.index},
        "engine_untrusted_or_caution_with_signal_label": float(
            (sig_any & (df["trust_state"] != "trusted")).sum() / max(sig_any.sum(), 1)
        ),
        "signal_label_given_engine_not_trusted": float(
            (sig_any & (df["trust_state"] != "trusted")).sum()
            / max((df["trust_state"] != "trusted").sum(), 1)
        ),
        "cause_share": df["cause"].value_counts(normalize=True).round(5).to_dict(),
    }


def run() -> dict:
    from divas_air.geo.adr import load_adr
    from divas_air.ingest.adr import class_map, load_side, read_member

    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    points = pd.read_parquet(POINTS_PATH)
    side = load_side()
    verdicts, vsrc = engine_verdicts(points)
    df = score(points, side, verdicts, load_adr().zones, class_map()["adr_group"])
    out = df.sort_values("adr_row", kind="stable")[OUTPUT_COLUMNS].reset_index(
        drop=True
    )
    for c in ("signal_anomaly_label", "behaviour_anomaly_label"):
        out[c] = out[c].astype("string")
    out.to_parquet(OUT_PARQUET, index=False)
    out.to_csv(OUT_CSV, index=False)
    manifest = json.loads(read_member("MANIFEST.json"))
    rep = report(df, verdicts, manifest, vsrc)
    rep["runtime_s"] = round(time.time() - t0, 1)
    REPORT_PATH.write_text(json.dumps(rep, indent=2, default=str))
    return rep
