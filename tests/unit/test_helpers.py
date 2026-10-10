"""The shared fixtures themselves. Module sessions add their own files next to this one."""

import numpy as np
from pyproj import Geod

from divas_air import schema
from tests.helpers import T0, error_m, make_track, renumber, shift_m

GEOD = Geod(ellps="WGS84")


def test_make_track_is_valid_and_geodesically_exact():
    a = make_track(speed_mps=5.0, n=120, dt=1.0)
    schema.validate(a)
    _, _, d = GEOD.inv(a["lon"].iloc[0], a["lat"].iloc[0], a["lon"].iloc[-1], a["lat"].iloc[-1])
    assert abs(d - 5.0 * 119) < 1e-6
    assert a["t"].iloc[0] == T0 and T0 % 5 == 0


def test_shift_m_moves_only_the_masked_fixes():
    a = make_track(labeled=True)
    b = shift_m(a, a["t"] >= T0 + 60, north=300.0)
    err = error_m(b)
    assert np.allclose(err[(a["t"] < T0 + 60).to_numpy()], 0.0, atol=1e-6)
    assert np.allclose(err[(a["t"] >= T0 + 60).to_numpy()], 300.0, atol=1e-6)


def test_renumber_restores_unique_seq():
    a = make_track()
    b = renumber(a[a["t"] != T0 + 10])
    assert b["seq"].tolist() == list(range(len(b)))
    schema.validate(b)
