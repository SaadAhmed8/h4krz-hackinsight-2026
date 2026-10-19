# src/dq_schema.py
from datetime import datetime, timezone, timedelta
from typing import Optional
import numpy as np
import pandas as pd
import pandera.pandas as pa

REQUIRED_COLUMNS = {"station_id", "ts_utc", "pm25", "source"}
OPTIONAL_COLUMNS = {"fetched_at_utc", "rh", "temp_c"}

# Explicit staleness limits (hours). Unknown sources MUST NOT default to 168h.
SOURCE_STALENESS_LIMITS_HOURS = {
    "openaq": 3.0,
    "openaq_v3": 3.0,
    "hawanama": 3.0,       # Hawanama is an active ground sensor feed; limit is 3h, not 7 days!
    "open-meteo": 168.0,
    "openmeteo": 168.0,
}


class ContractError(ValueError):
    """Raised when incoming cleaned data violates hard contract boundaries."""
    pass


def validate_contract_guards(
    df: pd.DataFrame, 
    reference_now_utc: Optional[datetime] = None
) -> pd.DataFrame:
    """
    Hard contract check before running DQ rules:
    - Verifies required columns and non-emptiness.
    - Rejects invalid timestamp types (strings, epochs) and timezone-naive series.
    - Catches Probe 09 & 12: Rejects any timestamp > reference_now_utc + 15 minutes.
    - Catches Probe 07: Rejects null/empty/blank station IDs.
    - Converts tz-aware timestamps strictly to UTC.
    """
    if not isinstance(df, pd.DataFrame):
        raise ContractError("Input must be a pandas DataFrame.")

    if df.empty:
        raise ContractError("Input DataFrame is completely empty (0 rows).")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ContractError(f"Missing required columns: {sorted(missing)}")

    out = df.copy()

    # 1. Reject invalid station_id (Probe 07)
    if out["station_id"].isna().any():
        raise ContractError("Column 'station_id' contains NaN/null values.")
    clean_stations = out["station_id"].astype(str).str.strip()
    if (clean_stations == "").any():
        raise ContractError("Column 'station_id' contains empty or whitespace-only strings.")
    out["station_id"] = clean_stations

    # 2. Strict ts_utc type and timezone verification (Probes 02, 03, 04, 05)
    ts_col = out["ts_utc"]
    if pd.api.types.is_string_dtype(ts_col) or pd.api.types.is_object_dtype(ts_col):
        raise ContractError(
            "Column 'ts_utc' is stored as strings/objects. "
            "Must be pre-parsed into datetime64[ns, UTC] by the cleaner layer."
        )
    if pd.api.types.is_integer_dtype(ts_col) or pd.api.types.is_float_dtype(ts_col):
        raise ContractError(
            "Column 'ts_utc' is numeric (epoch). "
            "Must be converted to datetime64[ns, UTC] before passing to DQ Agent."
        )
    if not isinstance(ts_col.dtype, pd.DatetimeTZDtype):
        raise ContractError(
            "Column 'ts_utc' is timezone-naive. Cleaning layer MUST attach timezone "
            "explicitly (e.g. UTC) before passing to DQ Agent."
        )
    out["ts_utc"] = out["ts_utc"].dt.tz_convert("UTC")

    # 3. Future Timestamp Guard (Catches Probe 09 +5h shift on fresh data, and Probe 12)
    now_utc = reference_now_utc or datetime.now(timezone.utc)
    max_allowed_ts = pd.Timestamp(now_utc + timedelta(minutes=15)).tz_convert("UTC") if now_utc.tzinfo else pd.Timestamp(now_utc + timedelta(minutes=15), tz="UTC")
    future_mask = out["ts_utc"] > max_allowed_ts
    if future_mask.any():
        max_seen = out.loc[future_mask, "ts_utc"].max()
        raise ContractError(
            f"Future timestamps detected! Max timestamp {max_seen} exceeds allowed ceiling "
            f"{max_allowed_ts} (now + 15m). Probable Pakistan local time labelled as UTC (+5h shift) "
            "or corrupt date."
        )

    # 4. Source Whitelist Check (Probe 15)
    known_sources = set(SOURCE_STALENESS_LIMITS_HOURS.keys())
    input_sources = set(out["source"].astype(str).str.lower().unique())
    unknown = input_sources - known_sources
    if unknown:
        raise ContractError(
            f"Unknown source(s) detected: {sorted(unknown)}. Allowed sources: {sorted(known_sources)}. "
            "Do not allow arbitrary sources to bypass staleness limits."
        )

    return out


CleanedLayerSchema = pa.DataFrameSchema(
    columns={
        "station_id": pa.Column(str, nullable=False),
        "ts_utc": pa.Column(nullable=False),
        "pm25": pa.Column(
            float,
            nullable=True,
            coerce=True,
            checks=[
                pa.Check.ge(0.0, name="pm25_min_0"),
                pa.Check.le(1000.0, name="pm25_max_1000"),
            ],
        ),
        "source": pa.Column(str, nullable=False),
        "rh": pa.Column(
            float,
            nullable=True,
            required=False,
            coerce=True,
            checks=[pa.Check.between(0.0, 100.0, name="rh_bounds")],
        ),
        "temp_c": pa.Column(
            float,
            nullable=True,
            required=False,
            coerce=True,
            checks=[pa.Check.between(-10.0, 55.0, name="temp_c_bounds")],
        ),
    },
    strict=False,
    coerce=True,
)


ProcessedDailySchema = pa.DataFrameSchema(
    columns={
        "row_id": pa.Column(str, nullable=False, unique=True),
        "station_id": pa.Column(str, nullable=False),
        "date_pkt": pa.Column(str, nullable=False),
        "pm25_mean": pa.Column(float, nullable=False, checks=pa.Check.between(0.0, 1000.0)),
        "n_valid_hours": pa.Column(int, nullable=False, checks=pa.Check.between(18, 24)),
        "target_next_day_pm25": pa.Column(float, nullable=True),
    },
    strict=False,
    coerce=True,
)
