import json

import pandas as pd

from divas_air import schema
from divas_air.models.splits import (
    SPLITS,
    check_splits,
    load_or_make_splits,
    make_splits,
    scene_strata,
)


def _windows(n_scenes=60):
    rows = []
    for i in range(n_scenes):
        sid = f"ground_{i:04d}"
        rows.append((sid, "plausible"))
        rows.append((sid, schema.CAUSES[1 + i % 6]))
    return pd.DataFrame(rows, columns=["scene_id", "label_cause"])


def test_split_is_a_stratified_partition(tmp_path):
    w = _windows()
    s = load_or_make_splits(w, tmp_path / "splits.json")
    check_splits(s, w)
    assert sum(len(s[k]) for k in SPLITS) == 60
    assert 30 <= len(s["train"]) <= 42


def test_split_is_seeded_and_reused(tmp_path):
    w = _windows()
    st = scene_strata(w)
    assert make_splits(st) == make_splits(st)
    path = tmp_path / "splits.json"
    first = load_or_make_splits(w, path)
    path.write_text(json.dumps({**first, "note": "kept"}))
    assert load_or_make_splits(w, path) == first
    assert "note" in json.loads(path.read_text())


def test_existing_split_missing_scenes_is_an_error(tmp_path):
    import pytest

    path = tmp_path / "splits.json"
    load_or_make_splits(_windows(30), path)
    with pytest.raises(ValueError, match="does not cover"):
        load_or_make_splits(_windows(60), path)
