"""Module 6 acceptance: the output contract for any track; three scenarios replay offline.

Spec: specs/06_api.md. Frozen: do not edit to make it pass.
"""

import json
import time

import numpy as np
import pandas as pd
import pytest

from divas_air import config, contract, params
from tests.helpers import LAT0, LON0, MODELS, REPLAY, T0, make_track, need, verdicts_path

EXAMPLES = config.ROOT / "contracts" / "examples"


# --- API ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    need(MODELS / "integrity_p2.txt")
    from divas_air.api.app import app

    with TestClient(app) as c:
        yield c


def api_points(track: pd.DataFrame, **extra) -> list[dict]:
    pts = []
    for r in track.itertuples():
        p = {
            "asset_id": r.asset_id,
            "t": r.t,
            "lat": r.lat,
            "lon": r.lon,
            "domain": r.domain,
            "gs_mps": r.gs_mps,
            "track_deg": r.track_deg,
            "heading_deg": r.heading_deg,
            "nacp": r.nacp,
            "nic": r.nic,
            "sil": r.sil,
        }
        p.update(extra)
        pts.append(p)
    return pts


def verdict_for(client, asset_id: str) -> contract.Verdict | None:
    out = contract.VerdictsOut.model_validate(client.get("/verdicts").json())
    hits = [v for v in out.verdicts if v.asset_id == asset_id]
    assert len(hits) <= 1, "one latest verdict per active track"
    return hits[0] if hits else None


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["stub"] is False
    assert body["schema_version"] == contract.SCHEMA_VERSION


def test_post_tracks_accepts_the_contract_example(client):
    r = client.post("/tracks", json=json.loads((EXAMPLES / "tracks_in.json").read_text()))
    assert r.status_code == 200
    ack = contract.IngestAck.model_validate(r.json())
    assert ack.accepted == 2 and ack.rejected == 0


def test_a_normal_track_gets_a_contract_verdict(client):
    track = make_track(track_id="live:api_bus_01:0", asset_class="bus", n=45, dt=2.0, t0=T0 + 1000)
    r = client.post("/tracks", json={"points": api_points(track, asset_class="bus")})
    assert contract.IngestAck.model_validate(r.json()).accepted == 45

    v = verdict_for(client, "api_bus_01")
    assert v is not None
    assert v.domain == "vehicle" and v.asset_class == "bus"
    assert v.track_id.startswith("live:api_bus_01:")
    assert v.trust_state == "trusted", "a clean constant-velocity track must be trusted"
    assert abs(v.position.speed_mps - 5.0) < 0.5

    hist = client.get("/verdicts", params={"track_id": v.track_id, "history_s": 300}).json()
    hist = contract.VerdictsOut.model_validate(hist).verdicts
    assert len(hist) >= 2 and all(h.track_id == v.track_id for h in hist)
    assert [h.t for h in hist] == sorted(h.t for h in hist)


def test_a_single_fix_still_gets_a_verdict(client):
    p = {
        "asset_id": "api_lonely",
        "t": T0 + 1100,
        "lat": LAT0 + 0.002,
        "lon": LON0,
        "domain": "vehicle",
        "asset_class": "follow_me",
    }
    assert client.post("/tracks", json={"points": [p]}).json()["accepted"] == 1
    v = verdict_for(client, "api_lonely")
    assert v is not None and v.confidence_level == "low"


def test_an_untyped_aircraft_is_class_other(client):
    track = make_track(
        track_id="live:abc123:0",
        domain="aircraft",
        asset_class="other",
        speed_mps=70.0,
        alt_m=600.0,
        n=30,
        t0=T0 + 1200,
    )
    pts = api_points(track, alt_baro_m=600.0, on_ground=False)
    assert client.post("/tracks", json={"points": pts}).json()["accepted"] == 30
    v = verdict_for(client, "abc123")
    assert v is not None and v.asset_class == "other"


def test_bad_points_are_rejected_one_by_one(client):
    good = {
        "asset_id": "api_ok",
        "t": T0 + 1300,
        "lat": LAT0,
        "lon": LON0,
        "domain": "vehicle",
        "asset_class": "bus",
    }
    no_class = {"asset_id": "api_noclass", "t": T0 + 1300, "lat": LAT0, "lon": LON0, "domain": "vehicle"}
    unknown = dict(good, asset_id="api_weird", asset_class="spaceship")
    ack = contract.IngestAck.model_validate(
        client.post("/tracks", json={"points": [good, no_class, unknown]}).json()
    )
    assert ack.accepted == 1 and ack.rejected == 2 and len(ack.errors) == 2
    assert verdict_for(client, "api_noclass") is None


def test_risk_zones_validate(client):
    zones = contract.RiskZones.model_validate(client.get("/risk-zones").json())
    assert all(f.properties.kind in ("static", "live", "forecast") for f in zones.features)


# --- replay bundle -------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> contract.ReplayManifest:
    return contract.ReplayManifest.model_validate_json(need(REPLAY / "manifest.json").read_text())


@pytest.fixture(scope="module")
def frames(manifest) -> list[contract.ReplayFrame]:
    path = need(REPLAY / manifest.frames_file)
    with open(path) as f:
        return [contract.ReplayFrame.model_validate_json(line) for line in f if line.strip()]


def by_id(manifest) -> dict[str, contract.ReplayEvent]:
    return {e.event_id: e for e in manifest.events}


def track_verdicts(frames, track_id, t0, t1):
    return [v for fr in frames if t0 <= fr.t <= t1 for v in fr.verdicts if v.track_id == track_id]


def test_bundle_is_complete(manifest, frames):
    assert len(frames) == manifest.n_frames >= 100
    t = np.array([fr.t for fr in frames])
    assert np.allclose(np.diff(t), manifest.step_s) and manifest.step_s == params.REPLAY_STEP_S
    assert np.isclose(t[0], manifest.t_start) and np.isclose(t[-1], manifest.t_end)
    ev = by_id(manifest)
    assert set(ev) == {"ev_phantom", "ev_real", "ev_sector"}
    assert ev["ev_phantom"].kind == "phantom_incursion"
    assert ev["ev_real"].kind == "real_incursion"
    assert ev["ev_sector"].kind == "sector_interference"
    assert min(len(fr.verdicts) for fr in frames[6:]) >= 20, "the scene has about 30 assets"


def test_phantom_incursion_reads_as_a_data_fault(manifest, frames):
    ev = by_id(manifest)["ev_phantom"]
    vs = track_verdicts(frames, ev.track_ids[0], ev.t_start, ev.t_start + 15)
    hit = [v for v in vs if v.quadrant == "data_fault"]
    assert hit, "the phantom incursion was not flagged as a data fault within 15 s"
    assert hit[0].action.code == "verify_radio"
    assert hit[0].severity.level in ("critical", "high")
    assert hit[0].cause in ("technical_error", "gnss_anomaly")
    assert hit[0].evidence, "an untrusted verdict needs evidence"


def test_real_incursion_reads_as_a_real_event(manifest, frames):
    ev = by_id(manifest)["ev_real"]
    vs = track_verdicts(frames, ev.track_ids[0], ev.t_start, ev.t_start + 15)
    hit = [v for v in vs if v.quadrant == "real_event"]
    assert hit, "the real incursion was not flagged as a real event within 15 s"
    assert hit[0].action.code == "act_now" and hit[0].cause == "behavioral_anomaly"
    assert hit[0].severity.level in ("critical", "high")
    during = track_verdicts(frames, ev.track_ids[0], ev.t_start, ev.t_end)
    assert all(v.trust_state != "untrusted" for v in during), "a real incursion must keep trusted data"


def test_sector_interference_collapses_into_one_area_alert(manifest, frames):
    ev = by_id(manifest)["ev_sector"]
    members = set(ev.track_ids)
    ok = False
    for fr in frames:
        if not ev.t_start <= fr.t <= ev.t_start + 60:
            continue
        ids = [v.area_alert_id for v in fr.verdicts if v.track_id in members and v.area_alert_id]
        if not ids:
            continue
        top = max(set(ids), key=ids.count)
        live = [
            f
            for f in fr.risk_zones.features
            if f.properties.kind == "live" and f.properties.area_alert_id == top
        ]
        if ids.count(top) >= 3 and live:
            ok = True
            assert live[0].properties.action and live[0].properties.action.code == "area_gnss_unreliable"
            break
    assert ok, "no area alert with three member tracks and a live halo within 60 s"


def test_no_critical_false_alarm_outside_the_events(manifest, frames):
    quiet = lambda t: all(not (e.t_start - 5 <= t <= e.t_end + 60) for e in manifest.events)  # noqa: E731
    calm = [v for fr in frames if quiet(fr.t) for v in fr.verdicts]
    assert calm
    bad = [v for v in calm if v.trust_state == "untrusted" and v.severity.level == "critical"]
    assert not bad, f"{len(bad)} critical untrusted verdicts outside the scripted events"
    assert np.mean([v.trust_state == "trusted" for v in calm]) >= 0.9


# --- engine ----------------------------------------------------------------------------


def test_engine_matches_the_batch_pipeline(manifest, frames):
    batch = pd.read_parquet(need(verdicts_path("demo")))
    online = pd.DataFrame(
        [(v.track_id, fr.t, v.integrity_raw, v.trust_state) for fr in frames for v in fr.verdicts],
        columns=["track_id", "t_end", "integrity_raw", "trust_state"],
    )
    m = online.merge(
        batch[["track_id", "t_end", "integrity_raw", "trust_state"]],
        on=["track_id", "t_end"],
        suffixes=("_on", "_b"),
    )
    assert len(m) >= 0.9 * len(online)
    assert (np.abs(m["integrity_raw_on"] - m["integrity_raw_b"]) <= 1.0).mean() >= 0.98
    assert (m["trust_state_on"] == m["trust_state_b"]).mean() >= 0.98


def test_step_latency_at_200_tracks():
    from divas_air.engine import TrustEngine

    need(MODELS / "integrity_p2.txt")
    engine = TrustEngine.from_disk()
    rng = np.random.default_rng(0)
    tracks = [
        make_track(
            track_id=f"live:lat_{i:03d}:0",
            asset_class="bus",
            n=90,
            t0=T0 + 2000,
            lat0=LAT0 + rng.uniform(-0.01, 0.01),
            lon0=LON0 + rng.uniform(-0.01, 0.01),
            course_deg=float(rng.uniform(0, 360)),
        )
        for i in range(200)
    ]
    pts = pd.concat(tracks, ignore_index=True)
    engine.ingest(pts[pts["t"] <= T0 + 2060])
    engine.step(T0 + 2060)  # warm-up
    took = []
    for k in range(1, 4):
        now = T0 + 2060 + 5 * k
        engine.ingest(pts[(pts["t"] > now - 5) & (pts["t"] <= now)])
        t0 = time.perf_counter()
        out = engine.step(now)
        took.append(time.perf_counter() - t0)
        assert len(out) == 200
    assert float(np.median(took)) < 1.0, f"step took {np.median(took):.2f} s for 200 tracks"
