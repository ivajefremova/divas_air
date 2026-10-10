"""Module 1 unit tests: flattened adsb.lol rows -> unified points."""

import numpy as np
import pandas as pd

from divas_air import params, schema
from divas_air.ingest import apply_type_overrides, asset_class_for, from_flat
from tests.helpers import T0, make_track

GAP = params.TRACK_GAP_SPLIT_S


def flat(
    track: pd.DataFrame, icao: str = "ABC123", typecode: str | None = "A320"
) -> pd.DataFrame:
    """A helpers track in the column layout of scripts/filter_adsblol.py."""
    n = len(track)
    return pd.DataFrame(
        {
            "icao24": icao,
            "ts": track["t"].to_numpy(),
            "lat": track["lat"].to_numpy(),
            "lon": track["lon"].to_numpy(),
            "on_ground": False,
            "alt_m": 500.0,
            "speed_mps": 70.0,
            "track_deg": 90.0,
            "vrate_mps": -3.5,
            "nic": np.where(np.arange(n) % 4 == 0, 8.0, np.nan),
            "nac_p": np.where(np.arange(n) % 4 == 0, 9.0, np.nan),
            "sil": np.where(np.arange(n) % 4 == 0, 3.0, np.nan),
            "callsign": "AZA123  ",
            "type": typecode,
        }
    )


def base(n: int = 40, dt: float = 2.0) -> pd.DataFrame:
    return flat(
        make_track(domain="aircraft", asset_class="narrowbody", n=n, dt=dt, alt_m=500.0)
    )


def test_output_is_schema_valid_and_keeps_values():
    pts, drops = from_flat(base(), "test")
    schema.validate(pts)
    assert len(pts) == 40 and drops["missing_t_lat_lon"] == 0
    assert (pts["asset_id"] == "abc123").all()
    assert (pts["track_id"] == "test:abc123:0").all()
    assert (pts["domain"] == "aircraft").all()
    assert (pts["gs_mps"] == 70.0).all() and (pts["alt_baro_m"] == 500.0).all()
    assert (pts["callsign"] == "AZA123").all()
    assert pts["alt_geom_m"].isna().all() and pts["heading_deg"].isna().all()
    assert (pts["asset_class"] == "narrowbody").all() and not pts[
        "type_overridden"
    ].any()


def test_long_silence_starts_a_new_segment():
    raw = base()
    raw.loc[20:, "ts"] += GAP + 1.0
    pts, _ = from_flat(raw, "test")
    assert pts["track_id"].tolist() == ["test:abc123:0"] * 20 + ["test:abc123:1"] * 20
    assert (
        pts.groupby("track_id")["seq"]
        .apply(list)
        .map(lambda s: s == list(range(20)))
        .all()
    )


def test_silence_at_the_limit_does_not_split():
    raw = base()
    raw.loc[20:, "ts"] += GAP - 2.0  # gap becomes exactly GAP
    pts, _ = from_flat(raw, "test")
    assert pts["track_id"].nunique() == 1


def test_out_of_order_and_duplicate_fixes_are_kept_in_arrival_order():
    raw = base()
    raw.loc[[5, 6]] = raw.loc[[6, 5]].to_numpy()  # swap two fixes
    raw = pd.concat([raw, raw.iloc[[10]]], ignore_index=True)  # duplicate
    pts, _ = from_flat(raw, "test")
    assert len(pts) == 41 and pts["track_id"].nunique() == 1
    assert np.array_equal(pts["t"].to_numpy(), raw["ts"].to_numpy())
    assert pts["seq"].tolist() == list(range(41))


def test_area_filter_then_split():
    raw = base(n=60, dt=10.0)
    lat0 = raw["lat"].iloc[0]
    raw.loc[20:49, "lat"] = lat0 + 1.0  # leaves the box for 300 s, comes back
    box = (lat0 - 0.1, 0.0, lat0 + 0.1, 90.0)
    pts, drops = from_flat(raw, "test", box=box)
    assert drops["outside_area"] == 30
    assert pts["track_id"].nunique() == 2


def test_rows_without_position_are_dropped_and_counted():
    raw = base()
    raw.loc[3, "lat"] = np.nan
    raw.loc[4, "ts"] = None
    pts, drops = from_flat(raw, "test")
    assert drops["missing_t_lat_lon"] == 2 and len(pts) == 38


def test_integrity_fields_forward_fill_within_track_only():
    raw = base()
    raw.loc[:, ["nac_p", "nic", "sil"]] = np.nan
    raw.loc[2, ["nac_p", "nic", "sil"]] = [9.0, 8.0, 3.0]
    raw.loc[20:, "ts"] += GAP + 1.0
    pts, _ = from_flat(raw, "test")
    first = pts[pts["track_id"].str.endswith(":0")]
    assert first["nacp"].iloc[:2].isna().all(), "never back-fill"
    assert (first["nacp"].iloc[2:] == 9.0).all()
    assert pts.loc[pts["track_id"].str.endswith(":1"), "nacp"].isna().all()


def test_on_ground_is_missing_when_altitude_is_unknown():
    raw = base()
    raw.loc[0, ["alt_m", "on_ground"]] = [np.nan, True]  # "ground"
    raw.loc[1, "alt_m"] = np.nan  # no altitude at all
    pts, _ = from_flat(raw, "test")
    assert pts["on_ground"].iloc[0] is True or pts["on_ground"].iloc[0]
    assert pd.isna(pts["on_ground"].iloc[1])
    assert not pts["on_ground"].iloc[2]


def test_unphysical_altitude_is_nulled_not_dropped():
    raw = base()
    raw.loc[7, "alt_m"] = 31821.12
    pts, drops = from_flat(raw, "test")
    assert len(pts) == 40 and drops["alt_baro_nulled_above_max"] == 1
    assert np.isnan(pts["alt_baro_m"].iloc[7])


def test_angles_wrap_to_0_360():
    raw = base()
    raw.loc[0, "track_deg"] = 360.0
    raw.loc[1, "track_deg"] = 365.0
    pts, _ = from_flat(raw, "test")
    assert pts["track_deg"].iloc[0] == 0.0 and pts["track_deg"].iloc[1] == 5.0
    assert pts["track_deg"].between(0, 360, inclusive="left").all()


def test_deterministic():
    a, _ = from_flat(base(), "test")
    b, _ = from_flat(base(), "test")
    pd.testing.assert_frame_equal(a, b)


def test_asset_class_for_unknown_and_missing():
    assert asset_class_for("A320") == "narrowbody"
    assert asset_class_for(" a320 ") == "narrowbody"
    assert asset_class_for("ZZZZ") == "other"
    assert asset_class_for(None) == "other"
    assert asset_class_for("") == "other"
    assert asset_class_for(np.nan) == "other"


def test_type_overrides_change_type_and_keep_raw():
    df = pd.DataFrame(
        {"asset_id": ["4d2101", "abc123"], "typecode_raw": ["DA42", "DA42"]}
    )
    out = apply_type_overrides(df)
    assert out["typecode"].tolist() == ["A320", "DA42"]
    assert out["typecode_raw"].tolist() == ["DA42", "DA42"]
    assert out["type_overridden"].tolist() == [True, False]
    assert out["asset_class"].iloc[0] == "narrowbody"


def test_untyped_aircraft_is_other():
    pts, _ = from_flat(base().assign(type=None), "test")
    assert (pts["asset_class"] == "other").all() and pts["typecode"].isna().all()


def test_t0_is_preserved():
    pts, _ = from_flat(base(), "test")
    assert pts["t"].iloc[0] == T0
