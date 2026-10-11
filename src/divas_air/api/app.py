"""Trust API (specs/06_api.md requirements 6-8).

    uvicorn divas_air.api.app:app --port 8000

The engine clock is data time: POST /tracks steps the engine through every
grid time between the previous clock and the latest fix seen, rounded down.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from divas_air import config, contract, params, schema
from divas_air.engine import TrustEngine, grid_ceil, grid_floor
from divas_air.ingest import apply_type_overrides

_DOMAIN_OF = {}
for _c, _d in pd.read_csv(config.ROOT / "data" / "reference" / "envelopes.csv")[
    ["category", "domain"]
].itertuples(index=False):
    _DOMAIN_OF[_c] = _d

_engine: TrustEngine | None = None
_lock = threading.Lock()


def engine() -> TrustEngine:
    global _engine
    if _engine is None:
        _engine = TrustEngine.from_disk()
    return _engine


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    engine()  # load models and layers at startup, not on the first request
    yield


app = FastAPI(
    title="Divas Air Trust API", version=contract.SCHEMA_VERSION, lifespan=_lifespan
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# --- conversion ----------------------------------------------------------------------


def _asset_class(p: contract.TrackPointIn) -> tuple[dict | None, str | None]:
    """(asset_class, type_overridden, typecode) or an error. A vehicle must state a known
    vehicle class; an aircraft takes asset_class, else its typecode (with the type
    overrides), else `other`."""
    if p.asset_class is not None:
        if p.asset_class not in schema.ASSET_CLASSES:
            return None, f"unknown asset_class {p.asset_class!r}"
        if _DOMAIN_OF.get(p.asset_class) != p.domain:
            return None, f"asset_class {p.asset_class!r} is not a {p.domain} class"
        return {
            "asset_class": p.asset_class,
            "type_overridden": False,
            "typecode": p.typecode,
        }, None
    if p.domain == "vehicle":
        return None, "a vehicle must state its asset_class"
    r = apply_type_overrides(
        pd.DataFrame({"asset_id": [p.asset_id], "typecode_raw": [p.typecode]})
    ).iloc[0]
    tc = None if pd.isna(r["typecode"]) else str(r["typecode"])
    return {
        "asset_class": str(r["asset_class"]),
        "type_overridden": bool(r["type_overridden"]),
        "typecode": tc,
    }, None


def _value_error(p: contract.TrackPointIn, t_ref: float) -> str | None:
    """Unit and clock checks of one point (a bad point must not break the batch or the clock)."""
    if not schema._T_MIN <= p.t <= schema._T_MAX:
        return f"t={p.t} is not UNIX seconds"
    if p.t > t_ref + params.TRACK_GAP_SPLIT_S:
        return (
            f"t={p.t} is more than {params.TRACK_GAP_SPLIT_S:.0f} s ahead of the batch"
        )
    for name in ("alt_baro_m", "alt_geom_m"):
        v = getattr(p, name)
        if v is not None and v > schema._ALT_MAX_M:
            return f"{name}={v} is not meters"
    return None


def to_points(
    body: contract.TracksIn, eng: TrustEngine
) -> tuple[pd.DataFrame, list[str]]:
    """Unified-schema points for the accepted points, and one error per rejected point.

    seq follows the order of the points in the request (arrival order), so
    out-of-order timestamps stay detectable."""
    rows, errors = [], []
    t_ref = float(np.median([p.t for p in body.points])) if body.points else 0.0
    for i, p in enumerate(body.points):
        cls, err = _asset_class(p)
        err = err or _value_error(p, t_ref)
        if err is not None:
            errors.append(f"point {i} ({p.asset_id}): {err}")
            continue
        track_id, seq = eng.live_ids(p.asset_id, p.t)
        d = p.model_dump()
        d.update(
            cls, track_id=track_id, seq=seq, source="live", typecode_raw=p.typecode
        )
        for a in ("track_deg", "heading_deg"):  # degrees in [0, 360)
            if d[a] is not None:
                d[a] = float(d[a]) % 360.0
        rows.append(d)
    if not rows:
        return pd.DataFrame(), errors
    df = schema.coerce_points(pd.DataFrame(rows))
    schema.validate(df)
    return df, errors


# --- routes --------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    eng = engine()
    return {
        "status": "ok",
        "stub": False,
        "schema_version": contract.SCHEMA_VERSION,
        "models": sorted(eng.bundle.boosters),
        "tracks": eng.n_tracks,
    }


@app.post("/tracks", response_model=contract.IngestAck)
def post_tracks(body: contract.TracksIn) -> contract.IngestAck:
    with _lock:
        eng = engine()
        pts, errors = to_points(body, eng)
        if len(pts):
            eng.ingest(pts)
            new_clock = grid_floor(float(eng.latest_fix_t))
            first = grid_ceil(float(pts["t"].min()))
            start = first if eng.clock is None else eng.clock + config.STRIDE_S
            # a long silence: step at most the last ENGINE_MAX_CATCHUP_STEPS grid times
            start = max(
                start,
                new_clock - (params.ENGINE_MAX_CATCHUP_STEPS - 1) * config.STRIDE_S,
            )
            for t in np.arange(start, new_clock + 1e-6, config.STRIDE_S):
                eng.step(float(t))
        return contract.IngestAck(
            accepted=len(pts), rejected=len(errors), errors=errors
        )


@app.get("/verdicts", response_model=contract.VerdictsOut)
def get_verdicts(
    track_id: str | None = None, history_s: float | None = Query(None, ge=0)
) -> contract.VerdictsOut:
    with _lock:
        eng = engine()
        if track_id is not None and history_s is not None:
            vs = eng.history(track_id, history_s)
        else:
            vs = eng.latest(track_id)
        return contract.VerdictsOut(t=eng.clock or 0.0, verdicts=vs)


@app.get("/risk-zones", response_model=contract.RiskZones)
def get_risk_zones() -> contract.RiskZones:
    with _lock:
        return engine().risk_zones()
