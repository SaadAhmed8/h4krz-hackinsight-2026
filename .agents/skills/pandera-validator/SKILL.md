---
name: pandera-validator
description: "Data quality schema validation with Pandera and hard contract guards for air quality timeseries. Enforces timezone-awareness, prevents PKT/UTC 5-hour shifts, and handles optional station telemetry."
---

# Pandera Validator Skill — HackInsight 2026

Expert rules and schema contracts for air quality telemetry validation using `pandera.pandas`. Built specifically around our repository standard: [dq_schema.py](file:///c:/Users/hasan/Downloads/Hack%20Insight/src/dq_schema.py).

## 1. Core Principles & Import Standards

Always use `pandera.pandas` import syntax to avoid deprecation warnings:

```python
import pandera.pandas as pa
from pandera.typing import Series
import pandas as pd
```

Never import top-level `import pandera as pa` when validating pandas DataFrames.

## 2. Hard Pre-Validation Contract Guards

Pandera schema validation alone can be bypassed or silently coerce data into faulty states if timestamps are ambiguous. All data ingestion must pass through hard contract guards **before** running statistical or Pandera checks.

### Critical Threat: Silent 5-Hour Shift Bug
Lahore uses Pakistan Standard Time (`Asia/Karachi`, UTC+5). If raw data arrives timezone-naive, pandas might interpret it as local time or assume UTC, causing a silent **5-hour phase shift**.
- Daily averages and evening smog spikes shift into the wrong calendar days.
- Target alignment (`target_next_day_pm25`) becomes completely invalid.

### Implementation Pattern

```python
REQUIRED_COLUMNS = {"station_id", "ts_utc", "pm25", "source"}
OPTIONAL_COLUMNS = {"fetched_at_utc", "rh", "temp_c"}

class ContractError(ValueError):
    """Raised when incoming data violates boundary contracts."""
    pass

def validate_contract_guards(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise ContractError("Input must be a pandas DataFrame.")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ContractError(f"Missing required columns: {sorted(missing)}")

    if df.empty:
        raise ContractError("Input DataFrame is completely empty.")

    out = df.copy()

    # Reject timezone-naive timestamps loudly
    if not isinstance(out["ts_utc"].dtype, pd.DatetimeTZDtype):
        raise ContractError(
            "Column 'ts_utc' is timezone-naive. Cleaning layer MUST attach timezone "
            "explicitly (e.g. UTC or Asia/Karachi) before passing to DQ Agent."
        )
    # Always normalize internal representation to UTC
    out["ts_utc"] = out["ts_utc"].dt.tz_convert("UTC")

    if "fetched_at_utc" in out.columns and out["fetched_at_utc"].notna().any():
        if not isinstance(out["fetched_at_utc"].dtype, pd.DatetimeTZDtype):
            raise ContractError("Column 'fetched_at_utc' must be timezone-aware if provided.")
        out["fetched_at_utc"] = out["fetched_at_utc"].dt.tz_convert("UTC")

    return out
```

## 3. Schemas

### CleanedLayerSchema (Incoming Station Telemetry)

Handles Hawanama stations that lack `rh` (relative humidity) or `temp_c` (temperature) sensors without crashing:

```python
CleanedLayerSchema = pa.DataFrameSchema(
    columns={
        "station_id": pa.Column(str, nullable=False, coerce=True),
        "ts_utc": pa.Column(nullable=False),  # TZ enforced by guard
        "pm25": pa.Column(
            float,
            nullable=True,
            coerce=True,
            checks=[
                pa.Check.ge(0.0, name="pm25_min_0"),
                pa.Check.le(1000.0, name="pm25_max_1000"),
            ],
        ),
        "source": pa.Column(str, nullable=False, coerce=True),
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
```

### ProcessedDailySchema (Hand-off to ML Model)

```python
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
```

## 4. Testing & Verification Checklist
1. Rejects naive `ts_utc` with `ContractError`.
2. Converts `Asia/Karachi` to UTC without hour shift.
3. Allows DataFrames lacking `rh` and `temp_c`.
4. Flags / cleans PM2.5 outside `[0.0, 1000.0]`.
5. Enforces lazy validation to report all failure cases when auditing.
