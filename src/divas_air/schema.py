import pandas as pd

TRACK_SCHEMA = {
    "track_id": "string",
    "asset_type": "string",
    "timestamp": "datetime64[ns, UTC]",
    "lat": "float64",
    "lon": "float64",
    "alt_m": "float64",
    "speed_mps": "float64",
    "heading_deg": "float64",
    "on_ground": "boolean",
    "quality": "float64",      # 0-1, NaN if the source has none
    "source": "string",        # adsblol | opensky | synthetic | adr
    "label_cause": "string",   # NaN for real data
}

def validate(df: pd.DataFrame) -> pd.DataFrame:
    missing = set(TRACK_SCHEMA) - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df = df[list(TRACK_SCHEMA)].astype(TRACK_SCHEMA)
    assert df["lat"].between(-90, 90).all() and df["lon"].between(-180, 180).all()
    return df.sort_values(["track_id", "timestamp"]).reset_index(drop=True)
