"""Reading-level degradation predicate, shared by the feature and fleet layers.

The rule is the one that reproduced GPSJam on the Baltic day
(`scripts/gpsjam_repro.py`, docs/DATA_INVENTORY.md "Degraded reading rule"):
a fix is degraded if its NACp is below 8. NACp is already forward-filled per
aircraft within a track by ingest. Windows and cells are judged on the
majority of readings, never on one (hard rule 4).
"""

from __future__ import annotations

import pandas as pd

from divas_air import params


def is_degraded_reading(points: pd.DataFrame) -> pd.Series:
    """True where the fix reports NACp < 8. A fix without NACp is not degraded (not observable)."""
    nacp = pd.to_numeric(points["nacp"], errors="coerce").astype("float64")
    return (nacp < params.DEGRADED_NACP_BELOW).fillna(False).astype(bool)


def is_eligible_reading(points: pd.DataFrame) -> pd.Series:
    """True once the fix's track has reported NACp >= 8 at or before the fix (causal).

    The GPSJam reproduction only counts aircraft that reported good accuracy at
    some point: transponders that never report a good NACp are not evidence of
    interference. Rows must be sorted by time within each track.
    """
    nacp = pd.to_numeric(points["nacp"], errors="coerce").astype("float64")
    good = (nacp >= params.DEGRADED_ELIGIBLE_NACP).astype("int8")
    return good.groupby(points["track_id"].to_numpy()).cummax().astype(bool)
