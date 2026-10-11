# Status

One row per module. Update it when you start and when you finish a module: state, date, the measured headline numbers, and anything the next module needs to know. Measured values only.

| # | Module | State | Updated | Headline numbers | Open items |
|---|---|---|---|---|---|
| 0 | Contracts | done | 2026-10-10 | 13 contract tests pass | |
| 1 | Ingest | done | 2026-10-10 | fco 1,108,346 rows / 12,688 tracks / 2,781 aircraft / 8 days, typed 97.4 %; baltic 285,211 / 1,730 / 628 / 1 day, typed 87.7 %; control 1,190,201 / 8,020 / 3,506 / 1 day, typed 87.8 %. Rows dropped: 0 (no missing t/lat/lon). Byte-identical reruns, about 12 s for all three | adr_mock, lira: no data; `alt_geom_m`, `heading_deg` 100 % NaN |
| 2 | Generator | done | 2026-10-10 | 840 scenes (800 ground x 600 s, 40 approach x 1 h), 9,253,309 points, 25,142 tracks; plausible 97.6 % of points; events per cause: technical_error 289, spoofing 236, degraded 230, behavioral 195 (incursion 72, deviate 63, speeding 60), gnss_anomaly 194, interference 169; anomalous points by cause: interference 66.8 %, spoofing 7.7 %, degraded 6.7 %, gnss_anomaly 6.6 %, behavioral 6.6 %, technical_error 5.6 %; plausible vehicle error median 2.85 m (open sky 1.51 m), RMS 4.55, p95 9.34; `make synth` about 220 s | `alt_geom_m` all NaN, so the altitude-drift part of gnss_anomaly and spoofing is a no-op; no over-dwell behavioral mode; technical_error jump always reverts (no held variant); some generator constants are inline in `synth/` instead of `params.py`; plausible share is 97.6 %, not 98 % (see notes) |
| 3 | Features | done | 2026-10-10 | Over-limit share on clean `fco` (windows with >= 4 fixes and any envelope ratio > 1.5): **0.058 %** (target < 0.1 %; P0 only 0.039 %); held-out days 0.063 %. Runtime: fco 1.1 M points in 31 s, all five sources and calibration in 10 min (synthetic 550 s). Windows: fco 917,001, baltic 410,727, control 2,182,132, synthetic 2,870,487, demo 3,751. Degraded-majority windows: baltic 10.9 %, control 0.07 %, fco 0.03 %. 72 thresholds, 26 fitted | Only depend on these after reading the decisions below: 5 interpretations of the spec keep fco under 0.1 %. All-NaN: `kin_accel_imp_ratio_max` (P1, held back), `sig_alt_div_*` (no `alt_geom_m`), `kin_heading_course_diff_max` on real data (no `heading_deg`). Vehicle taus are fitted on all synthetic scenes: rerun `--calibrate` after module 4 writes `splits.json` |
| 4 | Models | trained (retrained by module 5 with fleet features) | 2026-10-11 | Test split, 560,546 windows: integrity pass 2 AUROC **0.9891** / AUPRC 0.9578 (pass 1 0.9894 / 0.9583; naive baseline 0.8255 / 0.1302); ECE 0.041 -> 0.0006 after isotonic; cause macro-F1 **0.528** (0.508 without fleet; majority 0.141); behavioral median integrity 99.9, abnormal share 0.49; spoofing median normality 66.7. Trees p1 314 / p2 356 / cause 497. `make accept N=4` 20 pass | The blocker below was resolved by the human (thresholds refit on train scenes, commit f400943). The acceptance-verifier has not reviewed module 4 since training. Spoofing median normality 66.7 and behavioral abnormal share 0.49: check them against spec 04 targets |
| 5 | Fleet | done | 2026-10-11 | Baltic: **89 red of 109** qualifying cells (82 %; reference 82 / 109; GPSJam's (bad-1)/total formula on our cells gives exactly 82 / 109). Control: **0 of 172** cells above 2 % (reference 0 / 172). Test scenes: interference windows recognized 99.4 % (cause 99.4 %, area alert 64.7 %; n = 11,962; target >= 50 %); technical_error windows attributed to interference 0.0 %, with an area alert 0.6 % (n = 960; target < 30 %). Pipeline, all 5 sources: 6 min 31 s (synthetic 208 s). Retrain with fleet: 4 min 43 s | Forecast not wired into the flat table (no column); module 6 calls `halos.forecast_paths`. Demo phantom fault reads as `possible_spoofing` (module 4). Apron baseline is all-floor, so the noisy-cell protection is inactive. Generator places interference at the densest disk (module 2). See the module 5 notes |
| 6 | API | blocked (13 of 14 acceptance tests pass) | 2026-10-11 | Step at 200 tracks: **0.50-0.56 s** with a 60-75 s buffer (the acceptance case); 2.4 / 5.1 / 7.3 s with 300 / 600 / 900 s buffers (verifier). Engine vs pipeline on demo: **3,751 / 3,751** windows identical (integrity_raw, trust_state, cause, area_alert_id). Detect: ev_phantom `data_fault` + `verify_radio` + critical at **+5 s** but cause `possible_spoofing`; ev_real `real_event` + `act_now` at **+4.6 s**, never untrusted; ev_sector 7 members share one alert + live halo at **+5 s**. Quiet periods: 837 verdicts, 100 % trusted, 0 critical untrusted. Replay 121 frames, 5.6 MB, 47 s to build, byte-identical reruns | **Blocker (module 4):** phantom cause reads `possible_spoofing` in batch and engine alike; `test_phantom_incursion_reads_as_a_data_fault` fails. Phantom reads `act_now` at +45 to +60 s. Latency fails req. 4 at steady state. Red-team route (req. 14) not built. See module 6 notes |
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


### Module 4 (models), 2026-10-11: blocked before training

**Done and committed** (b29b471, f654d97):
- `artifacts/models/splits.json`. Scenes are stratified by kind (approach / ground) and by the rarest cause in the scene, seeded with `params.SEED`. Counts are 502 / 172 / 166 scenes (approach 23 / 10 / 7). Every split has every cause. No `base_track_id` crosses splits.
- Part A, `divas_air.scoring`: `violations`, `dimension_scores`, `normality_score`, `tau_of`. Part A, `scoring.baseline.naive_score`.
- Part B: `divas_air.models` (`load_bundle`, `ModelBundle`). `python -m divas_air.models.train` covers pass 1, the fleet hook with out-of-fold pass 1, pass 2, cause, isotonic and temperature calibration on calib, test metrics and the model card.
- Part C, `divas_air.verdict`: smoothing and hysteresis, normality state, confidence, severity, reported cause, evidence, action, `assemble`, `to_contract`.
- Unit tests: `test_scoring.py`, `test_models_splits.py`, `test_models_train.py` (trains on a small in-memory table, checks byte-identical reruns, runs the fleet hook with a fake module 5), `test_verdict.py`.
- LightGBM settings are in `params.py` (`LGB_*`, `ECE_BINS`).

**Blocker.** The overnight instructions say to write `splits.json` first, then refit the feature thresholds on training scenes only, then train any model. Steps 1 and 2 worked:
- The refit was computed: `features.calibrate.fit_thresholds()` reads `splits.json`.
- Only vehicle taus change, and only slightly. Examples: `kin_course_resid_max` 46.72 -> 47.04, `kin_course_resid_mean` 22.63 -> 22.77, `kin_speed_resid_rel_max` 0.7037 -> 0.7114, `kin_pos_jitter_m` 17.374 -> 17.387. Vehicle windows used: 2,183,823 -> 1,311,153.

Writing the result over `data/reference/dimension_thresholds.csv` was refused twice by the session's permission guard ("irreversible local destruction"). CLAUDE.md also says not to overwrite existing files in `data/reference/`, while section 6 of the contracts names that file as module 3's output. I did not work around the guard. Because the instruction says the refit comes before training, **no model was trained** and the Part 2 acceptance tests fail on missing artifacts.

**To unblock** (about 10 min total), from the repo root with the venv active:
1. `python -m divas_air.features --calibrate`. This rewrites the thresholds from train scenes, and its `fitted_on` column then says "train scenes". Commit it.
2. `python -m divas_air.models.train`
3. `make accept N=4`, then the acceptance-verifier. Report the numbers from `artifacts/models/model_card.json`.

`make train` runs steps 2 and 1 in that order. Run step 1 first by hand. The models read raw feature values, not the thresholds, so the order changes only the dimension scores, the evidence limits and the normality-axis numbers in the card.

#### Decisions for the human (module 4)

1. **Stratification key** for the split: (scene kind, rarest cause present). The spec only says "stratified so each split has every cause".
2. **Early stopping**: a grouped 20 % of train scenes picks the tree count, floored at `LGB_MIN_TREES` = 50. The final model is refit on all train rows with that count. The spec suggests 300 to 500 trees; early stopping may pick fewer.
3. **Class weights** are "balanced" (each class has equal total weight) for both the integrity and cause models. ECE before calibration will be high because of this. Isotonic calibration on calib corrects it.
4. **Pass-1 calibration for fleet degraded flags.** The out-of-fold pass-1 scores of train scenes go through the final model's isotonic map. That map is fitted on calib only.
5. **Apron baseline "clean train scenes"** means train scenes with no non-plausible window label.
6. **Naive baseline.** Only pairs with both fixes inside the window count. A pair with dt <= 0 contributes its jump term only, with no infinite speed. A fix is airborne when the domain is aircraft and `on_ground` is not true.
7. **Axes in the card** use pass-2 calibrated integrity, the one that drives the verdict. The acceptance test also checks pass 1 independently.
8. **Confidence** treats a NaN `tmp_gap_max_s` as the worst gap (c_gap = 0.25).
9. **Action texts** are in `verdict.ACTION_TEXT`. They name no numbers, so the "every number with a unit" rule is met trivially. `act_now` says "a {class} is moving unexpectedly in {zone}". Please review the wording before the demo.
10. **Repo-wide `make lint`** still fails only on the pre-existing issues in `scripts/` and frozen `tests/acceptance/`. `tests/unit/test_helpers.py` (not mine) has one format diff. The module 4 files are clean.

#### Leakage audit (leakage-auditor, 2026-10-11, code read plus runs; no models yet)

No leak found in module 4 code. Checked: scene-level split, input lists, leak guard before every fit, transition rows, calib-only calibration, out-of-fold stacking, real holdout, and baseline parity. The naive baseline on the test rows already measures **AUROC 0.8255, AUPRC 0.1302** (560,546 rows, none missing). Pass 2 must beat these.

Fixed in module 4 after the audit:
- `load_or_make_splits` used to re-split silently when the feature table gained a scene. It now raises, so a change to the split is always deliberate.
- Fleet features are now computed per scene. 10 pairs of approach scenes overlap in real time, 6 of them across splits, so pooling them would have mixed splits in the fleet cells.

**For the human: risks outside module 4, not fixed (modules 2 and 3 own them):**
1. **Generator tell: dropouts (MEDIUM-HIGH).**
   - Clean synthetic vehicles never have a gap over 10 s or a missing NACp. Interference and technical_error windows do, in 8.6 % and 11.1 % of windows.
   - Real clean fco aircraft have gaps over 10 s in 37.5 % of windows.
   - In the synthetic data, any gap therefore means "anomaly", which inflates vehicle AUROC and macro-F1 and the margin over the gap-blind naive baseline.
   - Fix in module 2: natural dropouts on clean tracks. Until then, also report vehicle metrics on windows without a gap over 10 s before putting a vehicle AUROC on a slide.
2. **Approach scenes: missing values mean sound (LOW-MEDIUM).**
   - Only tracks spanning more than 150 s are injected (`synth/approach.py`).
   - `sig_nacp_median` is NaN in 11.4 % of plausible windows but 0.6 % of interference windows.
   - Fix: also report approach metrics on windows with NACp and `tmp_n_points >= MIN_POINTS`.
3. **Aircraft thresholds.**
   - The aircraft thresholds are fitted on all non-held-out fco hours, including the real base tracks of calib and test approach scenes (6.1 % of fit windows are test-scene hours).
   - Effect: only the approach `ctx_app_*` taus, which feed `spoofing_median_normality`.
   - Fix in `features/calibrate.py`: exclude the calib and test approach hours.
   - Separately, the aircraft `ctx_app_lateral_dev_deg` tau of 57.5 deg effectively disables that check.
4. **In-sample apron baseline (LOW, mandated by spec).** Clean train scenes feed the apron baseline that their own fleet features are later tested against.
5. **Same airframes across splits (LOW).** 429 of 1,399 approach aircraft appear in more than one split, on different flights.
6. **The train-scene threshold refit leaks nothing into the models.** No model input reads the thresholds file, and the vehicle spatial and contextual taus are identical under both fits. The refit is still needed so the `fitted_on` provenance is correct, and the instruction requires it before training.

## ADR dataset (`adr_mock`, alternative layer set)

Done 2026-10-11; details in `docs/ADR_DATASET.md`.

- `python -m divas_air.ingest --source adr_mock` reads ADR's tar in place and writes 664,573 points in 603 tracks (one per asset_id, 2026-10-08, 1 Hz). No sample is dropped; 85 headings of 360 are wrapped to 0.
- Side table `data/processed/adr/adr_mock_side.parquet` (gitignored).
- `data/reference/adr_class_map.csv`: 6 exact, 17 approx, 4 unmatched classes (fork_lift, cargo_truck, gpu_unit, works_vehicle; 19 % of samples, no envelope check).
- `MapLayers.load(profile="adr")`: 339 ADR zones plus the airside boundary, ADR criticality and speed limits, and `layers.zone_access`. The default profile is unchanged.
- Open: mapfeat reads `zone_access.csv`, not `layers.zone_access`. ADR has no course, baro altitude or NACp, so heading, altitude-divergence and signal checks are blind on it. A per-sample output for ADR's scoring is still to be built.

### Module 5 (fleet, halos, pipeline), 2026-10-11

Checks: `make accept N=5` 10 pass, `make accept N=4` 20 pass (retrained models), `make contracts` 13 pass, `make unit` 101 pass. Module 5 files are ruff-clean. `make lint` still fails only on the pre-existing files (frozen `contract.py`, `registry.py`, `schema.py` formatting, `scripts/`, `tests/acceptance/`, `tests/unit/test_helpers.py`).

**Artifacts**
- `data/processed/fleet/{baltic,control}_regional_cells.parquet` (`make fleet`), `<source>_apron_cells.parquet` for every source (written by `pipeline.run`).
- `data/processed/fleet/baseline_apron.parquet`: 151 cells, all at a 0.0 degraded rate on clean train scenes, so every cell uses the 0.02 floor. Clean synthetic scenes have no chronically noisy cell, so the baseline test only matters on real data.
- `map/layers/halos_static.geojson`: 3 dissolved MultiPolygons (45 / 30 / 15 deg), 4.2 MB.
- `data/processed/verdicts/<source>.parquet` for baltic, control, demo, fco, synthetic. Share of windows with an area alert: synthetic 1.87 %, demo 10.0 % (all of it the `ev_sector` alert, one id, cell `891e862586fffff`; 271 of 282 interference windows), baltic 0.01 %, fco and control 0.00 %. Airborne traffic rarely puts 3 tracks in a 175 m cell, as the spec expects.
- Plausible test windows with an area alert: 0.52 %. These are clean tracks standing inside an interference area; they get the id but keep their own trust state.

**Model change from the fleet features** (retrain, same splits): pass-2 integrity AUROC 0.9891 against pass 1 0.9894. Fleet features do not improve detection, only attribution: cause macro-F1 0.508 -> 0.528, interference recall in the confusion matrix 11,259 -> 11,890 of 11,962, interference windows misread as degraded 630 -> 63.

#### Decisions for the human (module 5)

1. **Regional share formula.** The spec and the acceptance test use share = degraded / aircraft (89 red of 109). `scripts/gpsjam_repro.py` and GPSJam use (degraded - 1) / aircraft, which on our cells gives exactly the reference 82 / 109. I followed the spec. Both pass (>= 70 % red, control 0 above 2 %).
2. **Regional NACp fill and eligibility follow the reference script, not the causal per-track rule.** NACp is forward-filled per aircraft over the whole day (across track segments), and an aircraft is eligible if it ever reported NACp >= 8 that day. With the per-track fill from ingest only, there were 106 qualifying cells, not 109. The regional profile is an offline daily map, so non-causal is acceptable there. The apron profile is untouched by this.
3. **Area alert members** are all tracks whose latest-window cell lies in the alert's cells, degraded or not. A held alert (up to `bin_s` after the last flagged step) keeps its last cells and members. When a component overlaps two alive alerts, the older id (lexicographically smallest) survives.
4. **Fleet grouping in the pipeline.** On labeled sources the fleet layer runs per `scene_id` (as in training: approach scenes share real clocks); on real sources it runs on the whole source.
5. **In-sample pass 1 on train scenes in the pipeline.** Training builds train-scene fleet features from out-of-fold pass-1 scores; `pipeline.run` uses the final pass-1 model everywhere. Only test-scene verdicts are evaluated, so the test metrics are unaffected. **Module 8 must filter to `splits.json["test"]`** and never report on train or calib verdicts.
6. **Static halo level and error.** Band k covers distance <= height / tan(angle) minus the steeper band. `expected_error_m` = the generator model's median horizontal error at the band's crossing angle (1.177 x sqrt(1 + white^2) x `gnss.sigma_m`): 6.0 / 4.5 / 3.0 m. `level` = 1 - open-sky error / expected error: 0.75 / 0.67 / 0.50. Every OSM building gets rings, including 6 m default-height sheds. Simplified at 1 m (`params.HALO_SIMPLIFY_M`).
7. **Live halo label** is a fixed template with raw counts ("Area GNSS alert: 3 of 4 assets degraded").
8. **Forecast (P2)** is implemented in `halos.forecast_paths`: samples every 5 s up to 60 s, earliest-entry halo per track, moving tracks only (gs >= `MOVING_MPS`). It is not in the flat verdict table, because the contract's flat columns have no `early_warning`. Module 6 should set `Verdict.early_warning` from it.

#### For the next modules
- **Module 6 (engine):** call `fleet.cells_from_windows`, `fleet_features`, `area_alerts` and `alert_members` on the trailing `bin_s` of windows, with `pipeline.load_baseline()`. `area_alerts` assigns ids from the alert's first time and smallest cell (`area_<t>_<cell>`), so the engine must keep the alert state across steps (or re-run `area_alerts` over a trailing span longer than an alert) to keep ids stable. `pipeline.degraded_flags(features, bundle)` is the requirement-4 rule.
- One run of `python -m divas_air.pipeline --source demo` aborted at interpreter exit ("terminate called without an active exception", exit 134) after writing its output. Four reruns were clean. It looks like a LightGBM/OpenMP teardown race; watch for it in `make` chains.
- **Acceptance-verifier (2026-10-11): ready.** Requirements 1-13 and 15 met (7 and 13 by documented assumption), 14 partly met (no `early_warning`, P2). Regional cells match `data/processed/gpsjam_repro_*` cell by cell: identical `n_tracks` and `n_degraded` in all 109 Baltic and 172 control cells. Artifacts are deterministic. Its findings, and what I did with them:
  1. **Demo risk (module 4, not fixed here):** in `verdicts/demo.parquet`, 12 of 17 `ev_phantom` (single-track fault) windows report `possible_spoofing` (p about 0.84), only 1 reports `technical_error`, and 4 report `behavioral_anomaly` while `trusted`. The fleet features reach the cause model correctly; what drives `p_possible_spoofing` on this track needs a look in module 4 before the pitch. The demo labels must not be changed.
  2. **Apron baseline test is inactive in practice.** All 151 baseline cells are 0.0, so the 0.02 floor applies everywhere, and with n = 3 and 2 degraded p is about 0.0012 < alpha already. The "chronically noisy cell" protection exists in code and unit tests only. Do not claim it in the pitch. Real data shows no false alerts (fco 0, control 0, Baltic 2 alerts on 0.009 % of windows).
  3. `early_warning` is not produced: module 6 must set it from `halos.forecast_paths`.
  4. STATUS was stale when it read it; now updated.
- The verifier could not check pipeline/engine parity (module 6 does not exist yet) or alert-id behavior when 3 or more components merge and split (only the 1- and 2-component cases are tested).

#### Leakage audit (leakage-auditor, 2026-10-11)

No leak in module 5. The audit re-ran the reported numbers and they match. It confirmed by perturbation:
- A track's own degraded flag never changes its own `flt_*` row (flips on 8 tracks x 6 scenes changed 0 own rows).
- The features are causal (truncating at the median `t_end` gives 0 differences).
- Fleet groups never mix scenes or splits, and no label reaches the degraded flag or `area_alert_id`.
- The saved boosters' inputs equal `registry.MODEL_INPUTS_*`.

Area alerts are not leave-one-out, but they are not a model input.

**For the human, outside module 5 (not fixed):**
1. **Generator tell in `flt_n_others` (MEDIUM, module 2).** `synth/scene.py` places ground interference at the candidate disk with the most tracks.
   - Effect: interference rows average 11.5 other tracks against 6.6 on plausible rows, and 9.7 already before onset. `flt_n_others` alone gives AUROC 0.723 for interference against plausible.
   - It is the only fleet column whose removal moves pass-2 AUROC (0.9891 -> 0.9869), and it carries part of the cause macro-F1 gain (0.432 without any `flt_*`, 0.528 with them).
   - The real signal is `flt_deg_rate_loo` / `flt_deg_count_loo` (AUROC 0.994-0.996). `flt_cell_flagged_loo` and `flt_nbr_flagged_frac` have zero gain.
   - Smallest fix: pick the disk at random among those with >= 3 tracks, then regenerate and retrain. Or report cause F1 without `flt_n_others`.
2. **The interference vs technical_error contrast is partly true by construction.** The generator defines interference as co-located tracks degraded together. "99.4 % vs 0 %" on synthetic data should not be the slide's only evidence; module 8 should add the real Baltic day.
3. **Module 8 must filter verdicts to `splits.json["test"]`** and assert no train or calib scene is in the evaluated rows. Train scenes have in-sample pass 1, pass 2 and cause; calib scenes were used for calibration.
4. Approach scenes get no fleet signal (`flt_n_others` is 0 on every non-plausible approach row): approach interference rests on per-track features only.

### ADR per-sample result (`python -m divas_air.adr`), 2026-10-11

Details, rules and every assumption: `docs/ADR_DATASET.md` section 7. Package `src/divas_air/adr/`, its own tunables, no edits to engine modules or `params.py`. Output `data/processed/adr/asset_tracks_scored.{parquet,csv}` (gitignored, ADR row order, no positions), 17 s, byte-identical reruns. Dataset version 1.2.

- **ADR's speed and heading are computed from consecutive positions** (every sample, rounding error only). Dead reckoning from them cannot see position errors, so the detectors dead-reckon from the >= 5 s velocity implied by the positions (decision confirmed by the human). implausible_speed and heading_incoherent: 0 samples on ADR.
- Trust (engine integrity, adr layer profile): windows trusted 98.05 % / caution 1.84 % / untrusted 0.11 %.
- Signal labels: 2,207 samples (0.33 %, 72 tracks): multipath 1,331, frozen 637, altitude 162, jump 60, fix_loss 18. gnss_drift is not detectable from positions alone.
- Behaviour labels: 12,905 samples (1.94 %, 188 tracks): runway_incursion 9,549 (105 tracks), unauthorized_zone 1,876, overspeed 1,503, proximity 4, unexpected_stop 0. wrong_way is not detected (no direction; no corridor has a one-way share >= 80 %).
- **Suppressed phantoms: 0 on ADR** (no ADR position error falls on a zone violation). On synthetic vehicles: 268 runway-incursion and 6,222 unauthorized-zone samples suppressed.
- Detectors vs engine: of the 2,207 signal-labeled samples, the engine trusts 78 %.
- Synthetic recall: frozen 0.985, jump 0.741, multipath 0.859, zone violation 0.305, overspeed 0.252, fix_loss 0.057, drift 0. Precision is low (0.003 to 0.20; frozen 1.0) because the generator's noise floor is about 3x ADR's.
- Class map: fork_lift -> baggage_tractor, cargo_truck and gpu_unit -> bus, works_vehicle -> follow_me (approx). adr_mock was re-ingested.
- Open: 105 of 603 tracks carry runway_incursion (handling group in ADR's runway critical area). This rests on our group assumption; check it against "most tracks are regular".

### Module 6 (engine, Trust API, replay bundle), 2026-10-11

Checks:
- `make contracts`: 13 pass.
- `make unit`: 143 pass.
- `make accept N=6`: 13 pass, **1 fail** (`test_phantom_incursion_reads_as_a_data_fault`).
- Module 6 files are ruff-clean. `make lint` fails only on the pre-existing files.
- The acceptance-verifier reviewed the module. It confirmed exact parity, that no score is implemented twice, and a deterministic bundle. Its verdict is "not ready" because of the blocker below.

**What exists**
- `divas_air.engine.TrustEngine`: `from_disk`, `ingest`, `step`, `risk_zones`, `latest`, `history`, `live_ids`.
- `divas_air.api.app:app`: `POST /tracks`, `GET /verdicts` (`?track_id=`, `&history_s=`), `GET /risk-zones`, `GET /health`. CORS is open.
- `python -m divas_air.api.replay` writes `data/processed/demo/replay/{manifest.json,frames.jsonl}` (committed).

**How the engine works.** At each grid time it recomputes the module 3 features over each active track's kept points (`params.ENGINE_KEEP_S` = 900 s) and keeps the window at `now`. Then it runs, in order:
- `pipeline.degraded_flags`;
- `fleet.cells_from_windows`, `fleet_features` and `alert_members` over the trailing `bin_s` of windows;
- `fleet.area_alerts` over the flagged cells since the last flag-free silence of `bin_s` or more, so alert ids match the batch;
- `verdict.assemble` with the carried per-track state.

Additive hooks in other modules' files (the defaults keep the old behavior; the verifier checked that batch outputs are unchanged):
- `compute_features(..., until=)`: a window at the clock for a track silent for more than a stride.
- `assemble(..., init=)`, `smooth_and_state(init)`, `normality_state(init)`: smoothing and both state machines continue across steps.
- `halos.forecast_paths(..., shapes=)`: the static halos are parsed once (parsing them took about 2 s per step).

#### Blocker (module 4 owns the fix)

The `ev_phantom` cause is `possible_spoofing` (p 0.91 / 0.86 / 0.84 in the first windows; `p_technical_error` 0.08 to 0.15). The batch `verdicts/demo.parquet` gives the same cause, so the engine is not the cause. The label is correct: the phantom is a held 59 m jump, which fits spec 02's technical_error.

TreeSHAP, spoofing minus technical_error, at onset +5 s:
- `kin_speed_resid_mean` +1.83: about 5 straddling pairs out of 30 give a mean of 1.9 m/s, which looks like spoofing's persistent drift;
- `spa_route_dist_max_m` +0.76;
- `kin_speed_resid_max` (11.8 m/s) pushes toward technical_error at -0.76, but loses.

A larger demo jump does not fix it. Re-scoring the same phantom at 150 / 300 / 600 / 1000 m still gives spoofing in the first window every time. Training jumps are 125 to 2,000 m. On the test split, technical_error recall is 675 / 960, with 100 windows read as spoofing.

Spec 06 requirement 12 forbids patching the bundle. Possible fixes:
1. Module 3: a "step vs ramp" feature, for example the max residual over the mean residual, or the displacement over the window against its path length.
2. Module 2: more held jumps on parked assets, including 50 to 125 m.
3. Then retrain (`python -m divas_air.models.train`), `python -m divas_air.pipeline --source demo`, `python -m divas_air.api.replay`, `make accept N=4,5,6`.

#### Demo risks found by the verifier (not covered by tests)

1. **Phantom reads "act now" from onset +45 to +60 s** (modules 3/4).
   - Once the jump leaves the 30 s window, integrity_raw returns to 99.9 while the position still sits on the runway. Trust goes caution, then trusted; the verdict is `real_event`, `act_now`, critical.
   - The batch gives the same answer.
   - Fix: a "jump not reverted" signal against the `BUFFER_S` baseline (module 3), then a retrain.
2. **A clean catering truck (`demo:s42v12:0`) reads `real_event` / `act_now` / high at about T+200 to +215 s**, just before ev_real. Its scripted route crosses a building footprint ("83% of positions fall inside a building"). Owner: module 2 routes or the map layers.
3. **Step latency fails requirement 4 at steady state.** It is 0.5 s with 75 s of buffer but 2.4 s at 300 s and 7.3 s at 900 s.
   - Why: `compute_features` recomputes every window of the kept points at every step (rolling medians and the map join are 85 % of the time).
   - The spec's fallback, "recompute only tracks with new fixes", does not help: at 1 Hz every track has new fixes every step.
   - The real fix belongs in module 3: compute only the window at `until`, trim to `BUFFER_S + WINDOW_S`, and carry the dwell timer as state.
   - The offline replay (31 tracks, 600 s) is unaffected. The acceptance test passes.
4. A track silent for up to 300 s stays `trusted` (integrity about 94, low confidence). That is the model's call (module 4).
5. `tmp_nonmono_count` uses seq order over the whole track, so a batch window can see a fix from after t_end. The verifier found 8 technical_error windows on one synthetic track where the batch is untrusted and the engine is trusted. The evaluation of out-of-order faults is slightly optimistic (module 3).
6. Silent tracks keep their fleet presence in the engine, but the batch has no windows for them. `flt_n_others` differed on 102 of 7,540 windows of a long approach scene. Long-scene parity is still 99.85 % on integrity_raw and 99.87 % on trust_state.

Fixed after the verifier:
- A point with `t` outside UNIX seconds, `t` more than `TRACK_GAP_SPLIT_S` ahead of the batch median, or altitude above 20,000 m is rejected on its own. Before, it caused an HTTP 500 or moved the clock permanently.
- seq now follows request order, so out-of-order timestamps are visible.
- `track_deg` and `heading_deg` are wrapped to [0, 360).

#### Decisions for the human (module 6)

1. **Replay frames leave out static halos.** They are constant and 4.2 MB each, which would make about 500 MB of committed frames. Frames carry `live` and `forecast` zones. Static halos are in `map/layers/halos_static.geojson` (in git) and in `GET /risk-zones`.
   - `contracts/examples/replay_frame.json` shows a static zone inside a frame.
   - Forecast zones reference `static_elev*` ids.
   - **Tell the map team to load the static layer once**, or decide that frames must carry it.
2. **Every forecast is also an early warning.** `Verdict.early_warning` is set from `halos.forecast_paths` against the static and live halos: 1,380 forecasts in 121 frames, most toward static building shadows. If that is too noisy on the map, restrict forecasts to live halos.
3. **Clock on the first POST.** The clock is the latest fix rounded down to the grid, so a first POST with one fix off the grid steps nothing until a later fix crosses a grid time.
4. **Long gaps.** `POST /tracks` steps at most `ENGINE_MAX_CATCHUP_STEPS` = 720 grid times (1 h) per call.
5. **Points ahead of the batch.** A point more than `TRACK_GAP_SPLIT_S` ahead of its batch's median `t` is rejected as a bad timestamp. A whole batch far ahead is accepted, because data time may jump.
6. **ENGINE_KEEP_S = 900 s.** Features over a longer-lived track restart their dwell timer at the oldest kept fix.
7. **Event titles** in `api/replay.py` (`EVENTS`) are operator-facing text. Please review the wording.
8. **Red-team route (req. 14) not built.** The spec allows it only after everything else passes.
