# Specs

One spec per module. Each gives inputs, outputs, the interface, the steps in priority order, and the acceptance test. `00_contracts.md` binds all of them.

| # | Spec | Depends on | Acceptance criterion | Command |
|---|---|---|---|---|
| 0 | `00_contracts.md` | | frozen contracts are consistent | `make contracts` |
| 1 | `01_ingest.md` | 0 | `validate()` passes on every source | `make accept N=1` |
| 2 | `02_generator.md` | 0, map layers, error model; 1 for approach scenes | every cause present; noise drawn from the error model | `make accept N=2` |
| 3 | `03_features.md` | 1, `geo` from 2 | about 0 % over-limit on clean real traffic | `make accept N=3` |
| 4 | `04_models.md` | 2, 3 | beats the baseline; calibration error reported | `make accept N=4` |
| 5 | `05_fleet.md` | 3, 4 | flags the Baltic day, silent on the control | `make accept N=5` |
| 6 | `06_api.md` | 4, 5 | returns the output contract for any track; three scenarios replay offline | `make accept N=6` |
| 8 | `08_evaluation.md` | 4, 5 | regenerates every pitch figure from one command | `make accept N=8` |

Module 7 (Risk Map, demo replay UI, red-team button) belongs to the map team. It consumes `contracts/` and the replay bundle from module 6.

## Build order

Two tracks run in parallel from the start, in two terminals on the same checkout. They touch different directories, so they do not collide; commit often.

- Track A: `/build-module 1`, then `/build-module 3`, then `/build-module 4`
- Track B: `/build-module 2`, then (after 4) `/build-module 5`
- Then `/build-module 6` and `/build-module 8`, in either order or in parallel.

Module 2 builds the map-layer loader (`divas_air.geo`) first, because module 3 needs it for spatial and contextual features. Module 3 can start its kinetic, temporal and signal features on helper tracks before either is ready. Module 4 is the join.

The map team can start immediately: `make stub` serves the contract examples.

## Status

`docs/STATUS.md` is the live board. Each session updates its own row.
