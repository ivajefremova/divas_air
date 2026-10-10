"""Module 1 acceptance: every real source passes validate(), overrides applied.

Spec: specs/01_ingest.md. Frozen: do not edit to make it pass.
"""

import pandas as pd
import pytest

from divas_air import config, params, schema
from tests.helpers import need, points_path

REAL_SOURCES = ("fco", "baltic", "control")


@pytest.fixture(scope="module")
def fco() -> pd.DataFrame:
    return pd.read_parquet(need(points_path("fco")))


@pytest.mark.parametrize("source", REAL_SOURCES)
def test_validate_passes_on_every_source(source):
    df = pd.read_parquet(need(points_path(source)))
    assert len(df) > 1000, f"{source}: suspiciously few rows ({len(df)})"
    schema.validate(df, labeled=False)
    assert (df["source"] == source).all()
    assert (df["domain"] == "aircraft").all()
    assert not any(c in df.columns for c in schema.LABEL_COLUMNS), "real data must carry no labels"


def test_load_points_returns_the_canonical_frame(fco):
    from divas_air.ingest import load_points

    df = load_points("fco")
    schema.validate(df)
    assert len(df) == len(fco)


def test_track_ids_are_source_asset_segment(fco):
    parts = fco["track_id"].str.split(":", expand=True)
    assert parts.shape[1] == 3
    assert (parts[0] == "fco").all()
    assert (parts[1] == fco["asset_id"]).all()
    assert (fco["asset_id"] == fco["asset_id"].str.lower()).all()


def test_type_overrides_are_applied(fco):
    ov = pd.read_csv(config.REFERENCE / "type_overrides.csv")
    ov["icao24"] = ov["icao24"].str.lower()
    hit = fco[fco["asset_id"].isin(ov["icao24"])]
    assert hit["asset_id"].nunique() >= 1, "none of the overridden aircraft appears in fco"
    m = hit.merge(ov, left_on="asset_id", right_on="icao24", suffixes=("", "_ov"))
    assert (m["typecode"] == m["typecode_ov"]).all()
    assert m["type_overridden"].all()
    assert (m["asset_class"] == "narrowbody").all()
    assert (m["typecode_raw"] != m["typecode"]).all(), "typecode_raw must keep the declared type"
    assert not fco.loc[~fco["asset_id"].isin(ov["icao24"]), "type_overridden"].any()


def test_most_aircraft_are_typed(fco):
    per_aircraft = fco.groupby("asset_id")["asset_class"].first()
    assert (per_aircraft != "other").mean() >= 0.95


def test_asset_class_for():
    from divas_air.ingest import asset_class_for

    assert asset_class_for("A320") == "narrowbody"
    assert asset_class_for("B77W") == "widebody"
    assert asset_class_for("ZZZZ") == "other"
    assert asset_class_for(None) == "other"


def test_units_are_si(fco):
    airborne = ~fco["on_ground"].fillna(False).astype(bool)
    low = fco[(fco["alt_baro_m"] < 600) & fco["gs_mps"].notna() & airborne]
    assert len(low) > 500
    med = low["gs_mps"].median()
    assert 55 <= med <= 100, f"median speed below 600 m is {med:.1f}; expected m/s on final approach"
    assert fco["alt_baro_m"].max() < 15000, "altitudes look like feet"
    assert fco["vrate_mps"].abs().quantile(0.99) < 40, "vertical rates look like ft/min"


def test_fco_is_inside_the_approach_box(fco):
    lat_min, lon_min, lat_max, lon_max = config.APPROACH_BOX
    assert fco["lat"].between(lat_min, lat_max).all()
    assert fco["lon"].between(lon_min, lon_max).all()


def test_segments_split_on_long_silences(fco):
    g = fco.sort_values(["track_id", "t"])
    gap = g.groupby("track_id", sort=False)["t"].diff()
    assert gap.max() <= params.TRACK_GAP_SPLIT_S + 1e-6


def test_integrity_fields_are_present(fco):
    assert fco["nacp"].notna().mean() > 0.5
    assert fco["nic"].notna().mean() > 0.5


def test_sampling_matches_the_known_rate(fco):
    g = fco.sort_values(["track_id", "t"])
    dt = g.groupby("track_id", sort=False)["t"].diff().dropna()
    assert 1.0 <= dt.median() <= 6.0, f"median interval {dt.median():.2f} s; about 2.7 s expected"
