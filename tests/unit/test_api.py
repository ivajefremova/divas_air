"""Trust API routes on a stand-in engine (specs/06_api.md req. 6-8)."""

import pytest
from fastapi.testclient import TestClient

from divas_air import contract
from divas_air.api import app as api
from divas_air.engine import TrustEngine
from tests.helpers import LAT0, LON0, T0, make_track
from tests.unit.test_engine import StubBundle


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_engine", TrustEngine(None, StubBundle()))
    with TestClient(api.app) as c:
        yield c


def point(asset_id="veh_a", t=T0, **kw):
    return {
        "asset_id": asset_id,
        "t": t,
        "lat": LAT0,
        "lon": LON0,
        "domain": "vehicle",
        **kw,
    }


def test_health_is_not_the_stub(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["stub"] is False and body["tracks"] == 0


def test_bad_points_are_rejected_individually(client):
    pts = [
        point(asset_class="bus"),
        point("veh_b"),  # vehicle without a class
        point("veh_c", asset_class="spaceship"),
        point("veh_d", asset_class="narrowbody"),  # aircraft class on a vehicle
    ]
    ack = contract.IngestAck.model_validate(
        client.post("/tracks", json={"points": pts}).json()
    )
    assert (ack.accepted, ack.rejected, len(ack.errors)) == (1, 3, 3)


def test_aircraft_class_from_typecode_or_other(client):
    pts = [
        {**point("4ca7b5", typecode="B738"), "domain": "aircraft"},
        {**point("abc123"), "domain": "aircraft"},
    ]
    assert client.post("/tracks", json={"points": pts}).json()["accepted"] == 2
    vs = contract.VerdictsOut.model_validate(client.get("/verdicts").json()).verdicts
    cls = {v.asset_id: v.asset_class for v in vs}
    assert cls == {"4ca7b5": "narrowbody", "abc123": "other"}
    assert all(v.track_id == f"live:{v.asset_id}:0" for v in vs)


def test_a_90_s_batch_steps_the_clock_18_times(client):
    track = make_track(track_id="live:veh_e:0", n=91, t0=T0 + 5)
    pts = [
        point(
            "veh_e",
            t=r.t,
            lat=r.lat,
            lon=r.lon,
            asset_class="bus",
            gs_mps=5.0,
            track_deg=90.0,
        )
        for r in track.itertuples()
    ]
    client.post("/tracks", json={"points": pts})
    hist = client.get(
        "/verdicts", params={"track_id": "live:veh_e:0", "history_s": 300}
    ).json()
    hist = contract.VerdictsOut.model_validate(hist)
    assert hist.t == T0 + 95 and len(hist.verdicts) == 19
    assert [v.t for v in hist.verdicts] == [T0 + 5 * k for k in range(1, 20)]


def test_a_long_silence_starts_a_new_segment(client):
    client.post("/tracks", json={"points": [point(asset_class="bus")]})
    client.post("/tracks", json={"points": [point(t=T0 + 1000, asset_class="bus")]})
    vs = contract.VerdictsOut.model_validate(client.get("/verdicts").json()).verdicts
    assert [v.track_id for v in vs] == ["live:veh_a:1"]


def test_risk_zones_and_cors(client):
    r = client.get("/risk-zones", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "*"
    contract.RiskZones.model_validate(r.json())


def test_bad_values_are_rejected_without_moving_the_clock(client):
    pts = [
        point(asset_class="bus"),
        point("veh_ms", t=T0 * 1000, asset_class="bus"),  # milliseconds
        point("veh_far", t=T0 + 1e6, asset_class="bus"),  # far ahead of the batch
        point("veh_ft", asset_class="bus", alt_baro_m=35000.0),  # feet
    ]
    ack = contract.IngestAck.model_validate(
        client.post("/tracks", json={"points": pts}).json()
    )
    assert (ack.accepted, ack.rejected) == (1, 3)
    assert client.get("/verdicts").json()["t"] == T0


def test_seq_follows_arrival_and_angles_wrap(client):
    pts = [
        point(t=T0 + 1, asset_class="bus", track_deg=360.0),
        point(t=T0 + 3, asset_class="bus", heading_deg=-5.0),
        point(t=T0 + 2, asset_class="bus"),
    ]
    client.post("/tracks", json={"points": pts})
    p = api.engine()._pts.sort_values("seq")
    assert list(p["t"]) == [T0 + 1, T0 + 3, T0 + 2]
    assert p["track_deg"].iloc[0] == 0.0 and p["heading_deg"].iloc[1] == 355.0
