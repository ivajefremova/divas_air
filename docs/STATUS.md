# Status

One row per module. Update it when you start and when you finish a module: state, date, the measured headline numbers, and anything the next module needs to know. Measured values only.

| # | Module | State | Updated | Headline numbers | Open items |
|---|---|---|---|---|---|
| 0 | Contracts | done | 2026-10-10 | 13 contract tests pass | |
| 1 | Ingest | done | 2026-10-10 | fco 1,108,346 rows / 12,688 tracks / 2,781 aircraft / 8 days, typed 97.4 %; baltic 285,211 / 1,730 / 628 / 1 day, typed 87.7 %; control 1,190,201 / 8,020 / 3,506 / 1 day, typed 87.8 %. Rows dropped: 0 (no missing t/lat/lon). Byte-identical reruns, about 12 s for all three | adr_mock, lira: no data; `alt_geom_m`, `heading_deg` 100 % NaN |
| 2 | Generator | done | 2026-10-10 | 240 scenes (200 ground x 600 s, 40 approach x 1 h), 2,603,796 points, 8,732 tracks; plausible 98.1 % of points; anomalous points by cause: interference 49.1 %, spoofing 15.3 %, gnss_anomaly 10.1 %, technical_error 9.7 %, degraded 8.8 %, behavioral 7.0 %; 41 % of ground scenes fully clean; plausible vehicle error RMS 5.41 m (median 3.39, p95 11.11), lag-1 autocorrelation 0.93; byte-identical rerun, `make synth` 73 s | `alt_geom_m` all NaN, so the altitude-drift part of gnss_anomaly and spoofing is a no-op; no behavioral speeding or over-dwell mode; technical_error jump always reverts (no held variant); some generator constants are inline in `synth/` instead of `params.py` |
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
- **For module 3:** the GNSS error model is a parametric stand-in, because the Decimeter data is not in `data/`. Open-sky sigma is 1.5 m per axis, scaled up to 4x with building elevation angle. Vehicles report every 1 or 2 s; aircraft use empirical fco intervals (median 2.78 s). Stopped assets report `gs_mps` exactly 0, including during behavioral events.
- Approach interference uses a 2 to 6 km radius (sector of airborne traffic), not the ground 150 to 600 m.
- Demo: `ev_phantom` 65 to 125 s, `ev_real` 220 to 307 s, `ev_sector` 420 to 570 s (13 tracks hit, 6 inside H3 cell `891e862586fffff` for the whole event). Event times are relative to the scene start.
- Acceptance-verifier: all 18 requirements met or met by documented assumption. Its findings on the H3 margin, the behavioral gs signature and the interference ranges are fixed; the rest are listed as open items above.
