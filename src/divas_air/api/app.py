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


def to_points(
    body: contract.TracksIn, eng: TrustEngine
) -> tuple[pd.DataFrame, list[str]]:
    """Unified-schema points for the accepted points, and one error per rejected point."""
    rows, errors = [], []
    order = sorted(range(len(body.points)), key=lambda i: body.points[i].t)
    for i in order:
        p = body.points[i]
        cls, err = _asset_class(p)
        if err is not None:
            errors.append(f"point {i} ({p.asset_id}): {err}")
            continue
        track_id, seq = eng.live_ids(p.asset_id, p.t)
        d = p.model_dump()
        d.update(
            cls, track_id=track_id, seq=seq, source="live", typecode_raw=p.typecode
        )
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
