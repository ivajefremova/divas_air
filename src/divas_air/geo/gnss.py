"""GNSS error model: open-sky scale, obstruction ratio, NACp/NIC from accuracy.

ASSUMPTION: specs/02 asks for an error model derived from the Decimeter dataset,
which is not in `data/` (docs/DATA_INVENTORY.md). The relation here is parametric
(params.GNSS_*): error grows linearly with the highest building elevation angle,
from 1x in open sky to GNSS_OBSTRUCTED_RATIO at GNSS_FULL_OBSTRUCTION_DEG.
Module 5's static halos use the same `error_ratio`.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from divas_air import params

# 95 % horizontal accuracy (EPU) of a circular Gaussian with per-axis sigma s is ~2.45 s
EPU_PER_SIGMA = 2.45
# DO-260B: NACp upper bounds on EPU (m) -> NACp
_NACP_BOUNDS = (
    (3.0, 11),
    (10.0, 10),
    (30.0, 9),
    (92.6, 8),
    (185.2, 7),
    (555.6, 6),
    (926.0, 5),
    (1852.0, 4),
)
# NIC upper bounds on containment radius Rc (m) -> NIC
_NIC_BOUNDS = (
    (7.5, 11),
    (25.0, 10),
    (75.0, 9),
    (185.2, 8),
    (370.4, 7),
    (926.0, 6),
    (1852.0, 5),
    (3704.0, 4),
)


def error_ratio(elev_deg) -> np.ndarray:
    """Error scale relative to open sky for a given highest building elevation angle."""
    f = np.clip(
        np.asarray(elev_deg, dtype="float64") / params.GNSS_FULL_OBSTRUCTION_DEG,
        0.0,
        1.0,
    )
    return 1.0 + (params.GNSS_OBSTRUCTED_RATIO - 1.0) * f


def sigma_m(elev_deg) -> np.ndarray:
    """Per-axis 1-sigma position error in meters."""
    return params.GNSS_OPEN_SIGMA_M * error_ratio(elev_deg)


def _lookup(value, bounds, worst: int) -> np.ndarray:
    v = np.asarray(value, dtype="float64")
    out = np.full(v.shape, float(worst))
    for bound, code in reversed(bounds):
        out = np.where(v < bound, float(code), out)
    return out


def nacp_from_epu(epu_m) -> np.ndarray:
    return _lookup(epu_m, _NACP_BOUNDS, 3)


def nic_from_rc(rc_m) -> np.ndarray:
    return _lookup(rc_m, _NIC_BOUNDS, 3)


def integrity_from_sigma(sigma) -> tuple[np.ndarray, np.ndarray]:
    """(NACp, NIC) a receiver would report for a per-axis sigma.

    Rc = 100 m + 5 x EPU, so nominal fixes report NIC 8 as on `fco` (83 % of fixes).
    """
    epu = EPU_PER_SIGMA * np.asarray(sigma, dtype="float64")
    return nacp_from_epu(epu), nic_from_rc(100.0 + 5.0 * epu)


def gauss_markov(
    t, tau_s: float, rng: np.random.Generator, *, step_s: float = 0.5
) -> np.ndarray:
    """Unit-variance first-order Gauss-Markov process sampled at times `t` (any order).

    Simulated on a regular grid with the exact discretization, then interpolated.
    """
    t = np.asarray(t, dtype="float64")
    if len(t) == 0:
        return np.zeros(0)
    t0, t1 = float(t.min()), float(t.max())
    n = int(np.ceil((t1 - t0) / step_s)) + 2
    phi = np.exp(-step_s / tau_s)
    w = rng.standard_normal(n) * np.sqrt(1.0 - phi**2)
    w[0] = rng.standard_normal()  # stationary start
    x = lfilter([1.0], [1.0, -phi], w)
    return np.interp(t, t0 + step_s * np.arange(n), x)
