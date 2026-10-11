# Status

One row per module. Update it when you start and when you finish a module: state, date, the measured headline numbers, and anything the next module needs to know. Measured values only.

| # | Module | State | Updated | Headline numbers | Open items |
|---|---|---|---|---|---|
| 0 | Contracts | done | 2026-10-10 | 13 contract tests pass | |
| 1 | Ingest | done | 2026-10-10 | fco 1,108,346 rows / 12,688 tracks / 2,781 aircraft / 8 days, typed 97.4 %; baltic 285,211 / 1,730 / 628 / 1 day, typed 87.7 %; control 1,190,201 / 8,020 / 3,506 / 1 day, typed 87.8 %. Rows dropped: 0 (no missing t/lat/lon). Byte-identical reruns, about 12 s for all three | adr_mock, lira: no data; `alt_geom_m`, `heading_deg` 100 % NaN |
| 2 | Generator | done | 2026-10-10 | 840 scenes (800 ground x 600 s, 40 approach x 1 h), 9,253,309 points, 25,142 tracks; plausible 97.6 % of points; events per cause: technical_error 289, spoofing 236, degraded 230, behavioral 195 (incursion 72, deviate 63, speeding 60), gnss_anomaly 194, interference 169; anomalous points by cause: interference 66.8 %, spoofing 7.7 %, degraded 6.7 %, gnss_anomaly 6.6 %, behavioral 6.6 %, technical_error 5.6 %; plausible vehicle error median 2.85 m (open sky 1.51 m), RMS 4.55, p95 9.34; `make synth` about 220 s | `alt_geom_m` all NaN, so the altitude-drift part of gnss_anomaly and spoofing is a no-op; no over-dwell behavioral mode; technical_error jump always reverts (no held variant); some generator constants are inline in `synth/` instead of `params.py`; plausible share is 97.6 %, not 98 % (see notes) |
| 3 | Features | done | 2026-10-10 | Over-limit share on clean `fco` (windows with >= 4 fixes and any envelope ratio > 1.5): **0.058 %** (target < 0.1 %; P0 only 0.039 %); held-out days 0.063 %. Runtime: fco 1.1 M points in 31 s, all five sources and calibration in 10 min (synthetic 550 s). Windows: fco 917,001, baltic 410,727, control 2,182,132, synthetic 2,870,487, demo 3,751. Degraded-majority windows: baltic 10.9 %, control 0.07 %, fco 0.03 %. 72 thresholds, 26 fitted | Only depend on these after reading the decisions below: 5 interpretations of the spec keep fco under 0.1 %. All-NaN: `kin_accel_imp_ratio_max` (P1, held back), `sig_alt_div_*` (no `alt_geom_m`), `kin_heading_course_diff_max` on real data (no `heading_deg`). Vehicle taus are fitted on all synthetic scenes: rerun `--calibrate` after module 4 writes `splits.json` |
| 4 | Models | in progress | 2026-10-11 | AUROC, AUPRC vs baseline; macro-F1; ECE before and after | |
| 5 | Fleet | not started | | Baltic red / qualifying cells; control cells above 2 % | |
| 6 | API | not started | | step latency; seconds to detect each demo event | |
| 8 | Evaluation | not started | | false alarms per 1,000 track-minutes; median time to detect | |

## Notes

### Module 1 (ingest), 2026-10-10

- Inputs are the flattened, already-SI `data/processed/adsblol_{fco,jam,control}_*.parquet` files (`scripts/filter_adsblol.py`); `data/raw/` does not exist here. Ingest maps columns and does not convert units.
- Null shares after the per-track forward-fill of `nacp`/`nic`/`sil`:
  - fco: gs 1.1 %, nacp 2.9 %, nic 1.7 %, alt_baro 3.9 %, track 1.5 %, vrate 3.4 %
  - baltic: gs 22.4 %, nacp 16.5 %, nic 0.9 %, alt_baro 27.6 %, track 27.1 %, vrate 29.6 %
  - control: gs 1.2 %, nacp 2.8 %, nic 1.0 %, alt_baro 4.5 %, track 2.1 %, vrate 5.6 %
- Human decision: baro altitudes above the 20,000 m bound in `schema.validate` are set to NaN and counted, not dropped. This hit 148 control fixes of one C130 (icao 010078, 31,821 m reported).
- Human decision: `schema.LABEL_COLUMNS` was added as a public alias (commit 7075ad5); `test_01_ingest` reads it.
- `on_ground` is NA where the source gave neither "ground" nor an altitude. The filter script wrote False there.
- **For module 3:** real data has no out-of-order fixes, because the upstream script writes each trace sorted by time. Duplicate timestamps do occur (fco 302, baltic 5,502, control 169). Out-of-order signal comes from synthetic injection only.
- **For module 3:** `alt_geom_m` and `heading_deg` are all NaN because `filter_adsblol.py` never read them. Raw readsb traces may carry `alt_geom` and `true_heading`; this is unchecked because `data/raw/` is absent. Re-flattening the raw traces would bring back the altitude-divergence and heading-vs-track signal.
- `make lint` fails repo-wide on pre-existing issues: 9 in `scripts/`, 9 in frozen `tests/acceptance/` files. Module 1 files are clean.


### Module 2 (generator), 2026-10-10

- Per cause, points (approach / ground) and tracks (approach / ground):

  | Cause | Points, approach | Points, ground | Tracks, approach | Tracks, ground |
  |---|---|---|---|---|
  | degraded | 1,834 | 2,561 | 60 | 38 |
  | technical_error | 1,416 | 3,396 | 67 | 57 |
  | gnss_anomaly | 1,631 | 3,403 | 45 | 43 |
  | possible_interference | 387 | 24,055 | 39 | 464 |
  | possible_spoofing | 2,766 | 4,860 | 72 | 51 |
  | behavioral_anomaly | 0 | 3,510 | 0 | 36 |

- **For module 4:** anomalous points are only 1.9 % of all points. Expect few positive windows per cause, especially behavioral (36 events). Approach scenes keep the real fco positions as truth, so their plausible error is 0.
- **For module 3:** the GNSS error model is a parametric stand-in, because the Decimeter data is not in `data/`. Open-sky sigma is 1.5 m per axis (1.26 m after the follow-up scale below), scaled up to 4x with building elevation angle. Vehicles report every 1 or 2 s; aircraft use empirical fco intervals (median 2.78 s). Stopped assets report `gs_mps` exactly 0, including during behavioral events.
- Approach interference uses a 2 to 6 km radius (sector of airborne traffic), not the ground 150 to 600 m.
- Demo: `ev_phantom` 65 to 125 s, `ev_real` 220 to 307 s, `ev_sector` 420 to 570 s (13 tracks hit, 6 inside H3 cell `891e862586fffff` for the whole event). Event times are relative to the scene start.
- Acceptance-verifier: all 18 requirements met or met by documented assumption. Its findings on the H3 margin, the behavioral gs signature and the interference ranges are fixed; the rest are listed as open items above.

### Module 2 follow-up, 2026-10-10 (generator balance, speeding, noise scale)

- Before this change, `events.parquet` had these event counts: interference 39, behavioral 36, gnss_anomaly 88, degraded 98, spoofing 123, technical_error 124.
- Now there are 800 ground scenes (`params.SYNTH_GROUND_SCENES`). `EVENT_WEIGHTS` went from (0.17, 0.22, 0.17, 0.08, 0.20, 0.16) to (0.15, 0.21, 0.15, 0.16, 0.15, 0.18), in the order degraded, technical, gnss, interference, spoofing, behavioral. Interference needed about twice its old share to reach 150 events. Technical_error needed more weight to stay above 5 % of anomalous points: at weight 0.16 it was 4.9 % and requirement 13 failed.
- Events per cause (approach / ground):

  | Cause | Approach | Ground | Total | Anomalous points |
  |---|---|---|---|---|
  | degraded | 60 | 170 | 230 | 15,180 |
  | technical_error | 67 | 222 | 289 | 12,603 |
  | gnss_anomaly | 45 | 149 | 194 | 14,967 |
  | possible_interference | 12 | 157 | 169 | 150,737 |
  | possible_spoofing | 72 | 164 | 236 | 17,360 |
  | behavioral_anomaly | 0 | 195 | 195 | 14,927 |

- Plausible share is 97.6 % of points, below the old 98.1 %. The cause is interference: about 890 points per event, so 150 or more events cost about 1.6 % of all points. To get back to 98 %, try shorter interference events or more approach hours. I did neither, because this task did not ask for either.
- **Speeding** (`behavioral_anomaly`, `params_json.mode = "speeding"`): a vehicle drives its own route through a speed-limited zone at true speed = zone limit x U(1.2, 1.8). The speed stays below 0.95 x class max, slows in turns to stay inside the class turn rate, and the asset stops ahead of its original path until the original catches up. GNSS is clean (receiver error carried over). Points are labeled only where the true speed is above the limit of the zone the asset is in, so `t_onset` is the first over-limit fix. Speed limits exist only on service roads (mostly 8.3 m/s), so only `follow_me` (max 14) and `sar_vehicle` (max 25) can speed below their class max. Results: 60 events, ratio to the limit 1.20 to 1.79 (median 1.36), labeled points per event median 20.5, min 5. Module 3 detects it with `ctx_zone_speed_ratio_max`.
- **Noise scale.** Yes, the error model's absolute values were used unscaled: per-axis sigma 1.5 m gave an open-sky median horizontal error of 1.76 m (measured on 20 clean scenes). `params.GNSS_ERROR_SCALE = 0.84` now multiplies `GNSS_MODEL_OPEN_SIGMA_M` into `GNSS_OPEN_SIGMA_M` (1.26 m). Every consumer (`gnss.sigma_m`, NACp/NIC, the injection noise multiples in `inject.SIGMA0`) gets the same scale. Measured on the full set: open-sky median 1.51 m. Median by building elevation angle: 1.84 m (0 to 5 deg), 2.43 m (5 to 15), 3.54 m (15 to 30), 5.81 m (30 and up). The obstructed-to-open ratio is unchanged (3.22 both before and after on the 20-scene check). Open-sky NACp stays 10 (EPU 3.1 m).
- **For module 5:** static halos do not exist yet, so the scale is not applied to them in code. Compute `expected_error_m` from `gnss.sigma_m` (or `params.GNSS_OPEN_SIGMA_M x gnss.error_ratio`), not from `GNSS_MODEL_OPEN_SIGMA_M`, so the halos match the generator. The median horizontal error is 1.177 x sqrt(1 + GNSS_WHITE_FRAC^2) x sigma.
- Demo: the code and script are unchanged. `demo_events.parquet` is byte-identical. `demo.parquet` now carries the scaled nominal noise (and a scaled `ev_sector` noise multiple), because it uses the same error model.
- Checks: `make accept N=2` 18 passed, `make unit` 42 passed, `make contracts` 13 passed. `make lint` still fails only on the 18 pre-existing issues in `scripts/` and frozen `tests/acceptance/`. The Makefile calls a bare `python`, so run it with `PY=.venv/bin/python` (and the venv on PATH for `ruff`) unless the venv is active.


### Module 3 (features), 2026-10-10

Checks: `make accept N=3` 16 passed, `make unit` 64 passed, `make contracts` 13 passed. `make lint` still fails only on the 18 pre-existing issues in `scripts/` and in frozen `tests/acceptance/`; module 3 files are clean. The acceptance-verifier reviewed the module. I fixed its findings 1-9 and re-measured; the numbers above are after the fixes.

**Over-limit share on clean fco, step by step.** Each row adds one rule to the row above. Only a reading of the spec gets fco under the target, never a threshold change.

| Rule set | Share of scored windows over the limit |
|---|---|
| literal spec | 2.06 % |
| + aircraft get the taxi limit only on mapped LIRF taxi surfaces | 1.06 % |
| + no airborne turn-rate envelope for aircraft on the ground | 0.82 % |
| + a moving gs without a course is not a report | 0.77 % |
| + position-only fixes get no envelope ratios | 0.24 % |
| + `kin_accel_imp_ratio_max` held back (P1) | 0.058 % |

#### Decisions for the human

Each decision is recorded in the code and can be reverted on its own. The verifier re-ran the literal rule for each of decisions 1-4. Each one alone would put fco over 0.1 %.

1. **Taxi speed limit for aircraft only on mapped LIRF taxi surfaces.**
   - Rule: taxiway, apron, stand or holding point within `ZONE_BUFFER_M`, and off the runway buffer. Everywhere else (runways, unmapped airports) the air limit applies.
   - Why: 7,560 on-ground fco fixes at about 35 m/s are take-off and landing rolls, almost all at Ciampino (LIRA, 41.80 N 12.60 E). Ciampino is inside `APPROACH_BOX` but has no map.
   - Caveats: with `layers=None` the literal rule applies, so the engine and the pipeline must always pass `MapLayers`. A spoofed ground fix off the map is checked against the air limit.
   - Code: `features/__init__.py` `_arrays`; `mapfeat.taxi_surface_mask`.
2. **No airborne turn-rate envelope for aircraft on the ground.**
   - `kin_turn_rate_ratio_max` and `kin_turn_rate_imp_ratio_max` are NaN for aircraft ground fixes.
   - Why: `max_turn_rate_dps` (6 deg/s) is an airborne figure; `scripts/check_envelopes.py` validated it on airborne fixes only. A ground turn is bounded by `kin_turn_radius_ratio_max`, which still applies.
3. **A gs above `COURSE_MIN_MPS` reported without `track_deg` counts as not reported.**
   - Why: these are readsb's stale velocities. Examples: a taxi gs of 12 m/s held through a take-off roll; a single 124 m/s reading among 243 m/s readings.
   - Evidence: such readings are 0.4 % of all gs readings, but they sit next to 83 % of the reported-acceleration violations.
   - For module 1: the upstream filter probably ignores readsb's stale-velocity flag.
4. **Position-only fixes get NaN envelope ratios.**
   - Definition: no gs, no course, no NACp, and NIC missing or 0 ("Rc unknown").
   - What they are: 417 fco tracks, 10,656 fixes, consistent with MLAT or TIS-B. These are not GNSS reports, and their positions jump by hundreds of meters.
   - Their consistency and jitter features are still computed. The aircraft calibration leaves out windows without NACp.
5. **`kin_accel_imp_ratio_max` ships all-NaN** (P1, allowed by requirement 9).
   - Why: over 5 s pairs, the change of implied speed is dominated by ADS-B position and timestamp noise: 0.72 % over-limit on clean fco, still 0.21 % after decision 4.
   - Option: a 10 s base gave 0.27 % before decision 4 and 0.055 % on the other tracks. Re-enabling it needs a spec decision on the pair base. The per-fix value is still computed (`core.WITHHELD`).
6. **Map features only where the map exists.** Ground fixes get them inside `AIRPORT_BOX`, airborne fixes inside `APPROACH_BOX`. Elsewhere (Ciampino, Baltic, control) all spatial and contextual features are NaN, including `spa_zone_crit_max`. Module 4 and 5 severity must handle a NaN zone criticality.
7. **Type-violation crossings.** A non-runway zone the class may not enter does not count while the fix is also within `ZONE_OCCUPANCY_MARGIN_M` (10 m, the GNSS noise margin) of a zone the class may enter. Runway violations always count.
8. **The noise margin also applies elsewhere.** Off-zone, allowed-zone and zone-speed-limit membership use `ZONE_OCCUPANCY_MARGIN_M`.
   - Why: with strict containment, 19 % of clean synthetic vehicle windows were "off-zone" and 1.5 % had a violation. With the margin: 0.06 % and 0.001 %.
   - Cost: `ctx_type_violation` fires on 31 % of behavioral windows (some of those windows are speeding or deviation, not incursion).
9. **Final approach: a height cone the spec does not have.**
   - Selection: the runway is the aligned end (course within 30 deg, threshold ahead) with the nearest extended centerline. Then distance <= `APPROACH_FINAL_KM` applies, plus height <= tan(6 deg) x distance + 150 m (`APPROACH_CONE_*`).
   - Why: without the cone, 6,375 cruise overflights counted as "final", with criticality 1.0.
   - Result: lateral deviation p99 is 0.48 deg. The fitted p99.9 is still 57.5 deg: 0.4 % of final windows, at real final distances and low altitude. These may be circling or side-step approaches; I did not check them further.
10. **GPSJam eligibility in `sig_degraded_frac`.** It counts readings only once the track has reported NACp >= 8 (causal), via the new `degradation.is_eligible_reading`. Module 5 should use the same pair of functions. Effect on control degraded-majority windows: 2.27 % -> 0.07 %.
11. **Identity rule 1** also fires when an airline callsign meets a raw type that maps to `other` (unknown), not only `light`. Callsigns are carried forward within the track. All 4 known misidentified airliners are now flagged; 0.16 % of other fco windows fire (callsign prefixes BIO, P4L, OEF, ITY; 11 tracks).
12. **Calibration details.**
    - Fitted only on windows with >= `MIN_POINTS` fixes.
    - Aircraft windows must report NACp.
    - A feature with fewer than `THRESHOLD_MIN_N` (100) clean windows keeps the registry default. Example: `spa_route_dist_*` for aircraft had only 6 LIRF ground windows.
13. **`tmp_frozen_run_s`** counts from the start of the run of repeated positions, which may lie before the window. It is capped at `BASELINE_S`, so it stays inside the buffer.

#### Notes for the next modules

- **Module 4:**
  - Fitted aircraft taus are large because real ADS-B is noisy: `kin_speed_resid_max` 48 m/s, `kin_pos_jitter_m` 50 m, `tmp_gap_max_s` 213 s.
  - Clean synthetic over-limit share: aircraft 0.035 %, vehicles 0.086 %.
  - Median `kin_pos_jitter_m` by cause: plausible 2.7 m, interference 9.5 m, gnss_anomaly 7.7 m, degraded 7.2 m.
  - `ctx_zone_speed_ratio_max > 1.2` on 1.3 % of clean synthetic vehicle windows: the generator drives slightly over the 30 km/h service-road limit.
- **Control day (clean Europe):** 0.70 % envelope over-limit, led by `kin_vrate_ratio_max` (0.47 %) and "light"-class aircraft at about 200 m/s. This looks like type-to-class mapping outside Italy; not checked further.
- **Online engine (module 6):** baselines read fixes in (t_end - 330 s, t_end]; the dwell timer is per-track state (`mapfeat.dwell_seconds`). Call `compute_features` with `MapLayers`, or decision 1 changes kinetic values.
- Map features on fco: 3 ground fixes at LIRF in 8 days. The LIRF ground paths are exercised only on synthetic data and in unit tests.
