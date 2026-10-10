"""Regenerate contracts/*.schema.json and contracts/examples/*.json.

Run after any approved change to src/divas_air/contract.py:
    python scripts/make_contract_examples.py

The examples are hand-written illustrations of the four quadrants at Fiumicino.
Coordinates are approximate and for layout work only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from divas_air import contract as c  # noqa: E402
from divas_air.schema import CAUSES  # noqa: E402

OUT = ROOT / "contracts"
T0 = 1791900000.0  # 2026-10-12, illustrative


def probs(**kw: float) -> dict[str, float]:
    rest = (1.0 - sum(kw.values())) / (len(CAUSES) - len(kw))
    return {k: round(kw.get(k, rest), 4) for k in CAUSES}


def square(lat: float, lon: float, half_m: float) -> dict:
    dlat, dlon = half_m / 111_320.0, half_m / 83_000.0
    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in ring]]}


def verdicts() -> list[c.Verdict]:
    trusted = c.Verdict(
        track_id="fco:4ca7b5:0",
        asset_id="4ca7b5",
        domain="aircraft",
        asset_class="narrowbody",
        callsign="RYR4TK",
        t=T0,
        position=c.Position(lat=41.8010, lon=12.2460, alt_m=None, track_deg=164.0, speed_mps=7.2),
        integrity=96.0,
        integrity_raw=97.1,
        normality=100.0,
        dimensions=c.Dimensions(kinetic=100, temporal=100, spatial=100, contextual=100),
        trust_state="trusted",
        normality_state="expected",
        quadrant="trusted",
        confidence=0.93,
        confidence_level="high",
        cause="plausible",
        cause_probs=probs(plausible=0.94),
        severity=c.Severity(
            level="none", score=0.02, zone_id="twy_B", zone_name="Taxiway B", zone_criticality=0.5
        ),
        evidence=[],
        action=c.Action(code="none", text="No action."),
    )
    phantom = c.Verdict(
        track_id="synthetic:veh_017:0",
        asset_id="veh_017",
        domain="vehicle",
        asset_class="baggage_tractor",
        t=T0,
        position=c.Position(lat=41.8246, lon=12.2371, track_deg=71.0, speed_mps=6.0),
        integrity=8.0,
        integrity_raw=6.5,
        normality=0.0,
        dimensions=c.Dimensions(kinetic=0, temporal=62, spatial=35, contextual=0),
        trust_state="untrusted",
        normality_state="abnormal",
        quadrant="data_fault",
        confidence=0.81,
        confidence_level="high",
        cause="technical_error",
        cause_probs=probs(technical_error=0.78, gnss_anomaly=0.12),
        severity=c.Severity(
            level="critical",
            score=1.0,
            zone_id="rwy_16R_34L",
            zone_name="Runway 16R/34L",
            zone_criticality=1.0,
        ),
        evidence=[
            c.Evidence(
                feature="kin_speed_resid_max",
                dimension="kinetic",
                text="Position implies 41 m/s but the asset reports 6 m/s",
                value=35.0,
                limit=10.0,
                unit="m/s",
            ),
            c.Evidence(
                feature="kin_accel_imp_ratio_max",
                dimension="kinetic",
                text="Position implies an acceleration 6.2x the maximum for a baggage_tractor",
                value=6.2,
                limit=1.5,
                unit="ratio",
            ),
            c.Evidence(
                feature="ctx_type_violation_crit_max",
                dimension="contextual",
                text="A baggage_tractor is not authorized in Runway 16R/34L",
                value=1.0,
                limit=0.0,
                unit="0-1",
            ),
        ],
        action=c.Action(
            code="verify_radio", text="Verify the vehicle's position by radio before holding the runway."
        ),
    )
    real = c.Verdict(
        track_id="synthetic:veh_031:0",
        asset_id="veh_031",
        domain="vehicle",
        asset_class="fuel_truck",
        t=T0,
        position=c.Position(lat=41.8032, lon=12.2515, track_deg=255.0, speed_mps=6.4),
        integrity=95.0,
        integrity_raw=95.8,
        normality=0.0,
        dimensions=c.Dimensions(kinetic=100, temporal=100, spatial=41, contextual=0),
        trust_state="trusted",
        normality_state="abnormal",
        quadrant="real_event",
        confidence=0.90,
        confidence_level="high",
        cause="behavioral_anomaly",
        cause_probs=probs(behavioral_anomaly=0.88, plausible=0.07),
        severity=c.Severity(
            level="critical",
            score=1.0,
            zone_id="rwy_16L_34R",
            zone_name="Runway 16L/34R",
            zone_criticality=1.0,
        ),
        evidence=[
            c.Evidence(
                feature="ctx_type_violation_crit_max",
                dimension="contextual",
                text="A fuel_truck is not authorized in Runway 16L/34R",
                value=1.0,
                limit=0.0,
                unit="0-1",
            ),
            c.Evidence(
                feature="spa_route_dist_max_m",
                dimension="spatial",
                text="54 m from the nearest authorized route",
                value=54.0,
                limit=25.0,
                unit="m",
            ),
        ],
        action=c.Action(
            code="act_now", text="Act now: position data is sound and the vehicle is on the runway."
        ),
    )
    jammed = c.Verdict(
        track_id="synthetic:veh_044:0",
        asset_id="veh_044",
        domain="vehicle",
        asset_class="bus",
        t=T0,
        position=c.Position(lat=41.7958, lon=12.2552, track_deg=12.0, speed_mps=5.1),
        integrity=22.0,
        integrity_raw=19.0,
        normality=88.0,
        dimensions=c.Dimensions(kinetic=71, temporal=55, spatial=88, contextual=100),
        trust_state="untrusted",
        normality_state="expected",
        quadrant="silent_risk",
        confidence=0.58,
        confidence_level="medium",
        cause="possible_interference",
        cause_probs=probs(possible_interference=0.61, degraded=0.2, gnss_anomaly=0.1),
        severity=c.Severity(
            level="medium", score=0.39, zone_id="apron_E", zone_name="Apron E", zone_criticality=0.5
        ),
        evidence=[
            c.Evidence(
                feature="flt_deg_rate_loo",
                dimension="fleet",
                text="80% of other assets in this area are degraded at the same time",
                value=0.8,
                unit="ratio",
            ),
            c.Evidence(
                feature="tmp_gap_max_s",
                dimension="temporal",
                text="No position for 14 s",
                value=14.0,
                limit=10.0,
                unit="s",
            ),
        ],
        action=c.Action(
            code="area_gnss_unreliable", text="GNSS is unreliable on Apron E: confirm positions visually."
        ),
        area_alert_id="area_0001",
    )
    spoofed = c.Verdict(
        track_id="fco:3c6589:0",
        asset_id="3c6589",
        domain="aircraft",
        asset_class="narrowbody",
        callsign="DLH5MM",
        t=T0,
        position=c.Position(lat=41.9050, lon=12.2040, alt_m=640.0, track_deg=163.0, speed_mps=72.0),
        integrity=31.0,
        integrity_raw=28.0,
        normality=93.0,
        dimensions=c.Dimensions(kinetic=58, temporal=100, spatial=100, contextual=93),
        trust_state="untrusted",
        normality_state="expected",
        quadrant="silent_risk",
        confidence=0.52,
        confidence_level="medium",
        cause="possible_spoofing",
        cause_probs=probs(possible_spoofing=0.55, gnss_anomaly=0.3),
        severity=c.Severity(
            level="critical", score=0.69, zone_id=None, zone_name="Final approach", zone_criticality=1.0
        ),
        evidence=[
            c.Evidence(
                feature="sig_alt_div_dev_max_m",
                dimension="signal",
                text="GNSS altitude departs from barometric altitude by 85 m",
                value=85.0,
                unit="m",
            ),
            c.Evidence(
                feature="kin_speed_resid_mean",
                dimension="kinetic",
                text="Implied and reported speed disagree by 9 m/s on average over 30 s",
                value=9.0,
                limit=5.0,
                unit="m/s",
            ),
        ],
        action=c.Action(
            code="cross_check",
            text="Cross-check this approach against radar: behavior looks normal, position data does not.",
        ),
        early_warning=c.EarlyWarning(risk_zone_id="static_T3", eta_s=45.0),
    )
    return [trusted, phantom, real, jammed, spoofed]


def risk_zones() -> c.RiskZones:
    feats = [
        c.RiskZoneFeature(
            geometry=square(41.7995, 12.2495, 90),
            properties=c.RiskZoneProps(
                risk_zone_id="static_T3",
                kind="static",
                level=0.45,
                label="Signal shadow: Terminal 3",
                expected_error_m=8.0,
            ),
        ),
        c.RiskZoneFeature(
            geometry=square(41.7958, 12.2552, 300),
            properties=c.RiskZoneProps(
                risk_zone_id="live_area_0001",
                kind="live",
                level=0.85,
                label="Possible interference: Apron E",
                area_alert_id="area_0001",
                track_ids=["synthetic:veh_044:0", "synthetic:veh_045:0", "synthetic:veh_052:0"],
                action=c.Action(
                    code="area_gnss_unreliable",
                    text="GNSS is unreliable on Apron E: confirm positions visually.",
                ),
                t_start=T0 - 50,
                t_end=T0 + 10,
            ),
        ),
        c.RiskZoneFeature(
            geometry={"type": "LineString", "coordinates": [[12.2601, 41.7949], [12.2575, 41.7955]]},
            properties=c.RiskZoneProps(
                risk_zone_id="forecast_veh_061",
                kind="forecast",
                level=0.85,
                label="veh_061 enters the interference area in 25 s",
                track_ids=["synthetic:veh_061:0"],
                enters_risk_zone_id="live_area_0001",
                eta_s=25.0,
                t_start=T0,
                t_end=T0 + 25,
            ),
        ),
    ]
    return c.RiskZones(t=T0, features=feats)


def main() -> None:
    (OUT / "examples").mkdir(parents=True, exist_ok=True)
    for name, model in {
        "verdict": c.Verdict,
        "verdicts_out": c.VerdictsOut,
        "risk_zones": c.RiskZones,
        "tracks_in": c.TracksIn,
        "replay_manifest": c.ReplayManifest,
        "replay_frame": c.ReplayFrame,
    }.items():
        (OUT / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")

    vs, rz = verdicts(), risk_zones()
    out = c.VerdictsOut(t=T0, verdicts=vs)
    (OUT / "examples" / "verdicts.json").write_text(out.model_dump_json(indent=2) + "\n")
    (OUT / "examples" / "risk_zones.json").write_text(rz.model_dump_json(indent=2) + "\n")
    tracks = c.TracksIn(
        points=[
            c.TrackPointIn(
                asset_id="veh_017",
                t=T0,
                lat=41.8246,
                lon=12.2371,
                domain="vehicle",
                asset_class="baggage_tractor",
                gs_mps=6.0,
                track_deg=71.0,
                nacp=10,
                nic=8,
                sil=3,
            ),
            c.TrackPointIn(
                asset_id="4ca7b5",
                t=T0,
                lat=41.8010,
                lon=12.2460,
                domain="aircraft",
                typecode="B738",
                callsign="RYR4TK",
                alt_baro_m=None,
                gs_mps=7.2,
                track_deg=164.0,
                on_ground=True,
                nacp=10,
                nic=8,
                sil=3,
            ),
        ]
    )
    (OUT / "examples" / "tracks_in.json").write_text(tracks.model_dump_json(indent=2) + "\n")
    frame = c.ReplayFrame(t=T0, verdicts=vs, risk_zones=rz)
    (OUT / "examples" / "replay_frame.json").write_text(frame.model_dump_json(indent=2) + "\n")
    manifest = c.ReplayManifest(
        airport="LIRF",
        t_start=T0 - 300,
        t_end=T0 + 300,
        step_s=5,
        n_frames=121,
        events=[
            c.ReplayEvent(
                event_id="ev_phantom",
                kind="phantom_incursion",
                title="Phantom runway incursion",
                t_start=T0 - 200,
                t_end=T0 - 140,
                track_ids=["synthetic:veh_017:0"],
            ),
            c.ReplayEvent(
                event_id="ev_real",
                kind="real_incursion",
                title="Real runway incursion",
                t_start=T0 - 50,
                t_end=T0 + 10,
                track_ids=["synthetic:veh_031:0"],
            ),
            c.ReplayEvent(
                event_id="ev_sector",
                kind="sector_interference",
                title="Sector interference",
                t_start=T0 + 100,
                t_end=T0 + 250,
                track_ids=["synthetic:veh_044:0", "synthetic:veh_045:0", "synthetic:veh_052:0"],
            ),
        ],
    )
    (OUT / "examples" / "replay_manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    print(
        f"wrote {len(list(OUT.glob('*.json')))} schemas and {len(list((OUT / 'examples').glob('*.json')))} examples to {OUT}"
    )


if __name__ == "__main__":
    main()
