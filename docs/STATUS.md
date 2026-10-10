# Status

One row per module. Update it when you start and when you finish a module: state, date, the measured headline numbers, and anything the next module needs to know. Measured values only.

| # | Module | State | Updated | Headline numbers | Open items |
|---|---|---|---|---|---|
| 0 | Contracts | done | 2026-10-10 | 13 contract tests pass | |
| 1 | Ingest | done | 2026-10-10 | fco 1,108,346 rows / 12,688 tracks / 2,781 aircraft / 8 days, typed 97.4 %; baltic 285,211 / 1,730 / 628 / 1 day, typed 87.7 %; control 1,190,201 / 8,020 / 3,506 / 1 day, typed 87.8 %. Rows dropped: 0 (no missing t/lat/lon). Byte-identical reruns, about 12 s for all three | adr_mock, lira: no data; `alt_geom_m`, `heading_deg` 100 % NaN |
| 2 | Generator | done | 2026-10-10 | 840 scenes (800 ground x 600 s, 40 approach x 1 h), 9,253,309 points, 25,142 tracks; plausible 97.6 % of points; events per cause: technical_error 289, spoofing 236, degraded 230, behavioral 195 (incursion 72, deviate 63, speeding 60), gnss_anomaly 194, interference 169; anomalous points by cause: interference 66.8 %, spoofing 7.7 %, degraded 6.7 %, gnss_anomaly 6.6 %, behavioral 6.6 %, technical_error 5.6 %; plausible vehicle error median 2.85 m (open sky 1.51 m), RMS 4.55, p95 9.34; `make synth` about 220 s | `alt_geom_m` all NaN, so the altitude-drift part of gnss_anomaly and spoofing is a no-op; no over-dwell behavioral mode; technical_error jump always reverts (no held variant); some generator constants are inline in `synth/` instead of `params.py`; plausible share is 97.6 %, not 98 % (see notes) |
| 3 | Features | not started | | over-limit share on clean `fco`; runtime; features still NaN | |
| 4 | Models | not started | | AUROC, AUPRC vs baseline; macro-F1; ECE before and after | |
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
