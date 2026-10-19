# Domain Glossary — Air Quality Warehouse (HackInsight 2026)

This glossary establishes the ubiquitous language across all layers of the data warehouse: Ingestion, Storage, Cleaning, Processing, and Manifesting.

---

## 1. Domain Entities & Bounded Contexts

### Stations & Sensors (OpenAQ Context)
- **Station / Location (`location_id`)**: A physical environmental monitoring installation in Lahore. Identified uniquely by OpenAQ v3 location ID.
- **Sensor (`sensor_id`)**: A specific physical detector measuring a designated parameter (e.g., PM2.5, PM1, temperature, RH) attached to a station.
- **Provider**: The operational organization managing data telemetry (e.g. `AirGradient`, `Hawanama`).
- **Owner**: The institutional owner or custodian of the station (e.g., `The Urban Unit`, `PAQI`, or `unverified` for IEEE).
- **Licence**: Legal copyright and attribution terms governing sensor data. Standard: `CC BY 4.0`.

### Meteorology (Weather Context)
- **Open-Meteo ERA5**: Reanalysis weather data source covering Lahore coordinate grid (`31.52° N, 74.36° E`). Hourly parameters: `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `precipitation`.

---

## 2. Temporal Semantics

- **UTC Timestamp (`timestamp_utc`)**: All persistent data in the warehouse is strictly stored in ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`), timezone-aware.
- **PKT Day (`pkt_date`)**: The operational decision window for school administrators running midnight-to-midnight in Pakistan Standard Time (PKT, UTC+5, `Asia/Karachi`). Defined as:
  $$\text{PKT Date} = \text{Date of } (T_{\text{UTC}} + 5\text{ hours})$$
  *(Example: `19:00 UTC` on Oct 19 is `00:00 PKT` on Oct 20).*
- **18-of-24 Rule (`is_valid_day`)**: A `(station, pkt_date)` daily aggregation is statistically valid if and only if it contains $\ge 18$ valid hourly PM2.5 readings out of the 24 possible hours. If $< 18$ hours are present, `pm25_daily_mean = NaN` and `validity_flag = 'insufficient_hours'`.

---

## 3. Warehouse Layers & Schemas

### Layer 1: Raw Layer (`data/raw/`)
- Immutable raw JSON API responses directly saved upon HTTP receipt.
- Filename format: `openaq_{station_slug}_sensor_{sensor_id}_{param}_{timestamp}.json` and `weather_lahore_{start}_{end}_{timestamp}.json`.
- Never modified or deleted.

### Layer 2: Cleaned Layer (`data/cleaned/`)
- Standardized Parquet files per station (`station_{slug}.parquet`) and weather (`weather_cleaned.parquet`).
- Continuous hourly index: Missing hours are explicitly retained as `NaN` (no silent fills or drops).
- **Quality Log (`quality_log.csv`)**: Append-only log recording every cleaning action (`fix`, `fill`, `flag`, `drop`), target column, reason, and rows affected.
- Quality Flags:
  - `negative_value`: Reading $< 0\ \mu\text{g/m}^3$.
  - `extreme_value`: Reading $> 1000\ \mu\text{g/m}^3$.
  - `stuck_sensor`: Identical non-zero readings for $\ge 6$ consecutive hours.

### Layer 3: Processed Layer (`data/processed/`)
- **Hourly Joined (`hourly_all.parquet`)**: Station measurements joined with ERA5 meteorology on UTC hour.
- **Daily Station Mart (`daily.parquet`)**:
  - **Deterministic Station-Day Primary Key (`record_id`)**: A collision-resistant, reproducible identifier defined as:
    $$\text{record\_id} = \text{sha256}(\text{slug} + \text{"\_"} + \text{pkt\_date})[:16]$$
  - **Daily Aggregates**: `pm25_mean`, `n_valid_hours`, `is_valid_day`, weather means/extremes.
  - **Lag Features (No-Lookahead)**: `pm25_lag_1d` (yesterday's mean), `pm25_lag_7d_mean` (past 7-day rolling mean, strictly excluding today and future).
  - **Target Variable**: `target_next_day_pm25` (tomorrow's mean, strictly aligned to day $D+1$ if valid).

### Layer 4: Audit & Manifest (`manifest.csv`)
- Comprehensive integrity ledger with SHA-256 checksums, layer tags, row counts, and date ranges for all data warehouse artifacts.
