"""Window labels on labeled sources (specs/00_contracts.md section 4).

Labels are read here and nowhere else in the feature layer; they never feed a
feature. Unlike features they may look at the first fix after the window (the
empty-window rule).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from divas_air import params, schema
from divas_air.features.windows import Grid, Slices

ANOMALOUS = [c for c in schema.CAUSES if c != "plausible"]


def window_labels(
    lab: pd.DataFrame, code: np.ndarray, g: Grid, w: Slices
) -> dict[str, np.ndarray]:
    """`lab` holds the label columns of the sorted fixes and `code` their track codes."""
    cause = (
        lab["label_cause"].astype("string").fillna("plausible").to_numpy(dtype=object)
    )
    n_fix = len(cause)
    counts = np.stack([w.sum((cause == c).astype("float64")) for c in ANOMALOUS], -1)
    n = w.count()
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(n > 0, counts.sum(-1) / n, 0.0)
    top = np.array(ANOMALOUS, dtype=object)[
        np.argmax(counts, -1)
    ]  # first cause wins a tie

    # empty window: the fixes on both sides decide if they agree
    before = g.hi - 1
    after = g.hi
    has_after = (after < n_fix) & (code[np.minimum(after, n_fix - 1)] == g.w_track)
    c_before = cause[before]
    c_after = np.where(has_after, cause[np.minimum(after, n_fix - 1)], None)
    agree = (n == 0) & has_after & (c_before == c_after) & (c_before != "plausible")
    frac = np.where(agree, 1.0, frac)
    top = np.where(agree, c_before, top)

    positive = frac >= params.LABEL_POS_FRAC
    out = {
        "label_frac": frac,
        "label_cause": np.where(positive, top, "plausible"),
        "label_transition": (frac > 0) & (frac < params.LABEL_POS_FRAC),
    }

    # onset and event: the last fix in the window that carries an event; empty windows take the fix before
    ev = lab["label_event_id"].astype("string")
    has_ev = ev.notna().to_numpy()
    i_ev = w.argmax(np.where(has_ev, np.arange(n_fix, dtype="float64"), np.nan))
    i_ev = np.where((i_ev < 0) & agree, before, i_ev)
    ok = i_ev >= 0
    k = np.maximum(i_ev, 0)
    onset = lab["label_onset_t"].to_numpy(dtype="float64")
    out["label_onset_t"] = np.where(ok, onset[k], np.nan)
    out["label_event_id"] = pd.array(
        np.where(ok, ev.to_numpy(dtype=object)[k], None), dtype="string"
    )
    out["scene_id"] = lab["scene_id"].astype("string").to_numpy(dtype=object)[before]
    out["base_track_id"] = (
        lab["base_track_id"].astype("string").to_numpy(dtype=object)[before]
    )
    return out
