"""Verdict assembly (specs/04_models.md part C).

State machines run per track in time order. Evidence sentences are registry
templates filled with raw values; action texts are fixed per code.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from divas_air import contract, params, registry, schema
from divas_air.scoring import (
    DIM_COLUMNS,
    dimension_scores,
    normality_score,
    tau_of,
    violations,
)

KEYS = list(schema.WINDOW_KEYS)
P_COLUMNS = [f"p_{c}" for c in schema.CAUSES]
UNSOUND_P = [f"p_{c}" for c in schema.UNSOUND_CAUSES]
NORMALITY_FEATURES = [
    s.name
    for s in registry.REGISTRY.values()
    if s.scored and s.dimension in ("spatial", "contextual")
]

ACTION_TEXT = {
    "none": "No action needed.",
    "monitor": "Keep watching {asset}. No action needed yet.",
    "verify_radio": "Confirm the position of {asset} by radio before any clearance near {zone}.",
    "verify_visual": "Confirm the position of {asset} visually or with a second source.",
    "cross_check": "Cross-check the position of {asset} with a second source: its reported track is inconsistent.",
    "act_now": "Contact {asset} now: a {asset_class} is moving unexpectedly in {zone}.",
    "area_gnss_unreliable": "Treat GNSS positions near {zone} as unreliable. Confirm positions by radio or visually.",
}


# --- state machines ------------------------------------------------------------


def smooth_and_state(integrity_raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One track in time order -> (smoothed integrity, trust_state per window)."""
    raw = np.asarray(integrity_raw, dtype="float64")
    s = np.empty(len(raw))
    st = np.empty(len(raw), dtype=object)
    prev, state = None, None
    for k, r in enumerate(raw.tolist()):
        if prev is None:
            cur = r
        else:
            a = params.EMA_ALPHA_DOWN if r < prev else params.EMA_ALPHA_UP
            cur = a * r + (1 - a) * prev
        state = _next_trust(state, cur)
        s[k], st[k], prev = cur, state, cur
    return s, st


def _next_trust(state: str | None, s: float) -> str:
    if state == "untrusted":
        if s <= params.UNTRUSTED_EXIT:
            return "untrusted"
        return "trusted" if s > params.CAUTION_EXIT else "caution"
    if s < params.UNTRUSTED_ENTER:
        return "untrusted"
    if state == "caution":
        return "trusted" if s > params.CAUTION_EXIT else "caution"
    return "caution" if s < params.CAUTION_ENTER else "trusted"


def normality_state(normality: np.ndarray) -> np.ndarray:
    """One track in time order: abnormal below ABNORMAL_ENTER until above ABNORMAL_EXIT."""
    out = np.empty(len(normality), dtype=object)
    abnormal = False
    for k, n in enumerate(np.asarray(normality, dtype="float64").tolist()):
        abnormal = n <= params.ABNORMAL_EXIT if abnormal else n < params.ABNORMAL_ENTER
        out[k] = "abnormal" if abnormal else "expected"
    return out


def _per_track(values: np.ndarray, starts: np.ndarray, fn) -> list[np.ndarray]:
    """Apply `fn` to each track slice of `values` (rows grouped by track, time-sorted)."""
    ends = np.r_[starts[1:], len(values)]
    return [fn(values[s:e]) for s, e in zip(starts, ends, strict=True)]


# --- confidence, severity, cause ---------------------------------------------------


def _level(value: np.ndarray, levels, below: str) -> np.ndarray:
    out = np.full(len(value), below, dtype=object)
    for thr, name in sorted(levels, key=lambda x: x[0]):
        out[value >= thr - 1e-12] = name
    return out


def confidence(n_points, gap_max_s, cause_probs) -> tuple[np.ndarray, np.ndarray]:
    n = np.nan_to_num(np.asarray(n_points, dtype="float64"), nan=0.0)
    gap = np.asarray(gap_max_s, dtype="float64")
    c_points = np.clip(n / (2 * params.MIN_POINTS), 0.25, 1.0)
    c_gap = np.where(np.isnan(gap), 0.25, np.clip(1 - (gap - 5) / 25, 0.25, 1.0))
    cp = np.sort(np.asarray(cause_probs, dtype="float64"), axis=1)
    c_margin = np.where(cp[:, -1] - cp[:, -2] >= params.CAUSE_MARGIN - 1e-12, 1.0, 0.6)
    value = np.minimum(c_points, c_gap) * c_margin
    levels = ((params.CONF_HIGH, "high"), (params.CONF_MEDIUM, "medium"))
    return value, _level(value, levels, "low")


def zone_criticality(crit) -> np.ndarray:
    c = np.asarray(crit, dtype="float64")
    return np.where(np.isnan(c), params.CRITICALITY["low"], c)


def severity(integrity, normality, zone_criticality_) -> tuple[np.ndarray, np.ndarray]:
    i = np.asarray(integrity, dtype="float64")
    n = np.asarray(normality, dtype="float64")
    score = np.maximum(1 - i / 100, 1 - n / 100) * zone_criticality(zone_criticality_)
    score = np.clip(score, 0.0, 1.0)
    return score, _level(score, params.SEVERITY_LEVELS, "none")


def reported_cause(
    trust_state, normality_state_, cause_probs: pd.DataFrame
) -> pd.Series:
    trust = np.asarray(trust_state, dtype=object)
    abnormal = np.asarray(normality_state_, dtype=object) == "abnormal"
    cp = cause_probs[P_COLUMNS].to_numpy(dtype="float64")
    causes = np.asarray(schema.CAUSES, dtype=object)
    argmax_all = causes[cp.argmax(axis=1)]
    unsound_idx = [schema.CAUSES.index(c) for c in schema.UNSOUND_CAUSES]
    argmax_unsound = causes[unsound_idx][cp[:, unsound_idx].argmax(axis=1)]
    out = np.where(
        trust == "trusted",
        np.where(abnormal, "behavioral_anomaly", "plausible"),
        np.where(trust == "untrusted", argmax_unsound, argmax_all),
    )
    return pd.Series(out, index=cause_probs.index, name="cause", dtype=object)


# --- evidence ---------------------------------------------------------------------


def _clean(x):
    if x is None or x is pd.NA:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, (np.floating, np.integer)):
        return None if np.isnan(x) else x.item()
    return x


def _sentence(feature: str, row: dict) -> dict | None:
    spec = registry.REGISTRY[feature]
    if not spec.template:
        return None
    vals = {"v": _clean(row.get(feature))}
    for f in spec.template_fields():
        if f != "v":
            vals[f] = _clean(row.get(f))
    if any(vals.get(f) is None for f in spec.template_fields()):
        return None
    try:
        text = spec.template.format(**vals)
    except (ValueError, TypeError, KeyError):
        return None
    return {
        "feature": feature,
        "dimension": spec.dimension,
        "text": text,
        "value": None if vals["v"] is None else float(vals["v"]),
        "limit": tau_of(feature, str(row.get("aux_domain"))),
        "unit": spec.unit or None,
    }


def _pick(features_ranked, row: dict, k: int) -> list[dict]:
    out = []
    for f in features_ranked:
        if len(out) >= k:
            break
        s = _sentence(f, row)
        if s is not None:
            out.append(s)
    return out


def evidence(
    rows: pd.DataFrame,
    trust_state: np.ndarray,
    norm_state: np.ndarray,
    contrib: pd.DataFrame | None,
    viol: pd.DataFrame,
) -> list[list[dict]]:
    """Evidence lists for `rows` (contrib: TreeSHAP of the rows needing integrity evidence)."""
    out: list[list[dict]] = []
    records = rows.to_dict("records")
    viol_n = viol[NORMALITY_FEATURES]
    for i, row in enumerate(records):
        integ = trust_state[i] != "trusted"
        norm = norm_state[i] == "abnormal"
        if not integ and not norm:
            out.append([])
            continue
        k_int = (2 if norm else params.MAX_EVIDENCE) if integ else 0
        k_norm = (1 if integ else params.MAX_EVIDENCE) if norm else 0
        ev: list[dict] = []
        if integ and contrib is not None:
            c = contrib.iloc[i]
            ranked = c[c > 0].sort_values(ascending=False, kind="stable").index
            ev += _pick(ranked, row, k_int)
        if norm:
            v = viol_n.iloc[i]
            ranked = v[v > 0].sort_values(ascending=False, kind="stable").index
            ev += _pick(ranked, row, k_norm)
        out.append(ev[: params.MAX_EVIDENCE])
    return out


# --- action -------------------------------------------------------------------------


def action_codes(
    area_alert_id, trust_state, norm_state, quadrant, severity_level
) -> np.ndarray:
    trust = np.asarray(trust_state, dtype=object)
    abnormal = np.asarray(norm_state, dtype=object) == "abnormal"
    q = np.asarray(quadrant, dtype=object)
    sev_hi = np.isin(np.asarray(severity_level, dtype=object), ["critical", "high"])
    sev_med = np.isin(
        np.asarray(severity_level, dtype=object), ["critical", "high", "medium"]
    )
    alert = pd.Series(area_alert_id, dtype=object).notna().to_numpy()
    conds = [
        alert & (trust != "trusted"),
        (q == "data_fault") & sev_hi,
        q == "data_fault",
        (q == "real_event") & sev_hi,
        (q == "silent_risk") & sev_med,
        (trust != "trusted") | abnormal,
    ]
    codes = [
        "area_gnss_unreliable",
        "verify_radio",
        "verify_visual",
        "act_now",
        "cross_check",
        "monitor",
    ]
    return np.select(conds, codes, default="none").astype(object)


def action_text(code: str, row: dict) -> str:
    asset = (
        _clean(row.get("aux_callsign"))
        or _clean(row.get("aux_asset_id"))
        or "the asset"
    )
    zone = _clean(row.get("aux_zone_name")) or "this area"
    cls = _clean(row.get("aux_asset_class")) or "vehicle"
    return ACTION_TEXT[code].format(
        asset=str(asset).strip(), zone=zone, asset_class=cls
    )


# --- assembly -------------------------------------------------------------------------


def assemble(
    features: pd.DataFrame,
    bundle,
    fleet: pd.DataFrame | None = None,
    area_alerts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Flat verdict table (specs/00_contracts.md section 6), one row per input row, input order."""
    f = features.reset_index(drop=True)
    if fleet is not None:
        f = f.drop(columns=[c for c in registry.FLEET_COLUMNS if c in f]).merge(
            fleet[KEYS + registry.FLEET_COLUMNS], on=KEYS, how="left"
        )
    if area_alerts is not None and len(area_alerts):
        f = f.drop(columns=["area_alert_id"], errors="ignore").merge(
            area_alerts[KEYS + ["area_alert_id"]].drop_duplicates(KEYS),
            on=KEYS,
            how="left",
        )
    elif "area_alert_id" not in f:
        f["area_alert_id"] = None
    f["_order"] = np.arange(len(f))
    f = f.sort_values(["track_id", "t_end"], kind="stable").reset_index(drop=True)
    n = len(f)

    p2 = bundle.p_unsound(f, pass_=2)
    integrity_raw = 100.0 * (1.0 - p2)
    cp = bundle.cause_probs(f)
    viol = violations(f)
    dims = dimension_scores(f, viol)
    normality = normality_score(dims).to_numpy()

    tid = f["track_id"].astype(str).to_numpy()
    starts = (
        np.flatnonzero(np.r_[True, tid[1:] != tid[:-1]]) if n else np.array([], int)
    )
    sm = _per_track(integrity_raw, starts, smooth_and_state)
    integrity = np.concatenate([a for a, _ in sm]) if n else np.empty(0)
    trust = np.concatenate([b for _, b in sm]) if n else np.empty(0, object)
    norm_st = (
        np.concatenate(_per_track(normality, starts, normality_state))
        if n
        else np.empty(0, object)
    )
    quadrant = np.where(
        trust != "untrusted",
        np.where(norm_st == "expected", "trusted", "real_event"),
        np.where(norm_st == "expected", "silent_risk", "data_fault"),
    )
    conf, conf_level = confidence(
        f.get("tmp_n_points", pd.Series(np.nan, index=f.index)),
        f.get("tmp_gap_max_s", pd.Series(np.nan, index=f.index)),
        cp.to_numpy(),
    )
    crit = zone_criticality(
        f.get("spa_zone_crit_max", pd.Series(np.nan, index=f.index))
    )
    sev, sev_level = severity(integrity, normality, crit)
    cause = reported_cause(trust, norm_st, cp).to_numpy()

    need = trust != "trusted"
    contrib = None
    if need.any():
        c = bundle.contributions(f[need], pass_=2)
        contrib = pd.DataFrame(0.0, index=f.index, columns=c.columns)
        contrib.loc[need] = c.to_numpy()
    flagged = need | (norm_st == "abnormal")
    ev_lists = [[] for _ in range(n)]
    if flagged.any():
        idx = np.flatnonzero(flagged)
        ev = evidence(
            f.iloc[idx],
            trust[idx],
            norm_st[idx],
            None if contrib is None else contrib.iloc[idx],
            viol.iloc[idx],
        )
        for i, e in zip(idx, ev, strict=True):
            ev_lists[i] = e

    codes = action_codes(f["area_alert_id"], trust, norm_st, quadrant, sev_level)
    aux = [c for c in registry.AUX_COLUMNS if c in f]
    recs = f[aux].to_dict("records")
    texts = [action_text(c, r) for c, r in zip(codes, recs, strict=True)]

    out = pd.DataFrame(
        {
            "track_id": f["track_id"].to_numpy(),
            "t_end": f["t_end"].to_numpy(dtype="float64"),
            "integrity_raw": integrity_raw,
            "integrity": integrity,
            "normality": normality,
        }
    )
    for c in DIM_COLUMNS:
        out[c] = dims[c].to_numpy()
    out["trust_state"] = trust
    out["normality_state"] = norm_st
    out["quadrant"] = quadrant
    out["confidence"] = conf
    out["confidence_level"] = conf_level
    out["cause"] = cause
    for c in P_COLUMNS:
        out[c] = cp[c].to_numpy()
    out["severity_score"] = sev
    out["severity_level"] = sev_level
    out["zone_criticality"] = crit
    out["action_code"] = codes
    out["action_text"] = texts
    out["area_alert_id"] = (
        f["area_alert_id"]
        .astype(object)
        .where(f["area_alert_id"].notna(), None)
        .to_numpy()
    )
    out["evidence_json"] = [json.dumps(e) for e in ev_lists]
    for c in aux:
        out[c] = f[c].to_numpy()
    for c in schema.WINDOW_LABEL_COLUMNS:
        if c in f:
            out[c] = f[c].to_numpy()
    out["_order"] = f["_order"].to_numpy()
    out = out.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    return out


def _opt_float(x) -> float | None:
    x = _clean(x)
    return None if x is None else float(x)


def to_contract(row) -> contract.Verdict:
    r = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    track_id = str(r["track_id"])
    domain = _clean(r.get("aux_domain")) or "vehicle"
    callsign = _clean(r.get("aux_callsign"))
    return contract.Verdict(
        track_id=track_id,
        asset_id=str(_clean(r.get("aux_asset_id")) or track_id.split(":")[1]),
        domain=domain,
        asset_class=str(_clean(r.get("aux_asset_class")) or "other"),
        callsign=None if callsign is None else str(callsign).strip() or None,
        t=float(r["t_end"]),
        position=contract.Position(
            lat=float(r["aux_lat"]),
            lon=float(r["aux_lon"]),
            alt_m=_opt_float(r.get("aux_alt_m")),
            track_deg=_opt_float(r.get("aux_track_deg")),
            speed_mps=_opt_float(r.get("aux_gs_mps")),
        ),
        integrity=float(np.clip(r["integrity"], 0, 100)),
        integrity_raw=float(np.clip(r["integrity_raw"], 0, 100)),
        normality=float(np.clip(r["normality"], 0, 100)),
        dimensions=contract.Dimensions(
            **{d[2:]: float(np.clip(r[d], 0, 100)) for d in DIM_COLUMNS}
        ),
        trust_state=r["trust_state"],
        normality_state=r["normality_state"],
        quadrant=r["quadrant"],
        confidence=float(r["confidence"]),
        confidence_level=r["confidence_level"],
        cause=r["cause"],
        cause_probs={c: float(r[f"p_{c}"]) for c in schema.CAUSES},
        severity=contract.Severity(
            level=r["severity_level"],
            score=float(r["severity_score"]),
            zone_id=_clean(r.get("aux_zone_id")),
            zone_name=_clean(r.get("aux_zone_name")),
            zone_criticality=float(r["zone_criticality"]),
        ),
        evidence=[contract.Evidence(**e) for e in json.loads(r["evidence_json"])],
        action=contract.Action(code=r["action_code"], text=r["action_text"]),
        area_alert_id=_clean(r.get("area_alert_id")),
    )
