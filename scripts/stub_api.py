"""Stub Trust API for the Risk Map team: same routes and shapes as the real one.

Serves the fixed examples in contracts/examples/ so the map can be built before
module 6 exists. Run from the repo root:

    uvicorn scripts.stub_api:app --port 8000 --reload

Routes: POST /tracks, GET /verdicts, GET /risk-zones, GET /health.
Swap to the real API by pointing the map at `divas_air.api.app:app`; nothing
else changes, because both validate against src/divas_air/contract.py.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from divas_air import contract as c  # noqa: E402

EX = ROOT / "contracts" / "examples"
_VERDICTS = c.VerdictsOut.model_validate_json((EX / "verdicts.json").read_text())
_ZONES = c.RiskZones.model_validate_json((EX / "risk_zones.json").read_text())

app = FastAPI(title="Divas Air Trust API (stub)", version=c.SCHEMA_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "stub": True, "schema_version": c.SCHEMA_VERSION}


@app.post("/tracks", response_model=c.IngestAck)
def post_tracks(body: c.TracksIn) -> c.IngestAck:
    return c.IngestAck(accepted=len(body.points), rejected=0)


@app.get("/verdicts", response_model=c.VerdictsOut)
def get_verdicts(track_id: str | None = None) -> c.VerdictsOut:
    now = time.time()
    vs = [
        v.model_copy(update={"t": now})
        for v in _VERDICTS.verdicts
        if track_id is None or v.track_id == track_id
    ]
    return c.VerdictsOut(t=now, verdicts=vs)


@app.get("/risk-zones", response_model=c.RiskZones)
def get_risk_zones() -> c.RiskZones:
    return _ZONES.model_copy(update={"t": time.time()})


if __name__ == "__main__":
    print(json.dumps(health()))
