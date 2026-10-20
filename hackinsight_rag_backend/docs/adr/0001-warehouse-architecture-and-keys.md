# ADR 0001: Three-Layer Data Warehouse Architecture & Deterministic Keys

## Status
Accepted

## Context
The HackInsight 2026 air quality forecasting problem requires robust data ingestion from OpenAQ v3 (10 Lahore monitoring stations) and Open-Meteo ERA5 reanalysis weather data. Downstream consumers include a data-quality agent, a forecasting model, a RAG agent, an hourly Prefect orchestrator, and a Hugging Face dashboard.

Key design challenges:
1. Temporal consistency: Air quality decisions occur on Pakistan Standard Time (PKT, UTC+5) school days, while upstream feeds report in UTC.
2. Missing data & gaps: Incomplete sensor coverage must be explicit (18-of-24 rule) without data loss or silent imputation.
3. Idempotency & incremental loading: Re-running pipeline runs must not re-fetch historical data or cause key collisions.
4. Deterministic Primary Keys: Downstream joins, marts, and models require stable, collision-free identifiers for `(station, pkt_date)` records across pipeline reruns.

## Decision

1. **Three-Layer Storage**:
   - **Raw (`data/raw/`)**: Immutable JSON responses tagged with UTC fetch timestamp and metadata.
   - **Cleaned (`data/cleaned/`)**: Station-level Parquet series reindexed to complete regular UTC hourly grids, with flagged anomalies recorded in `quality_log.csv`. Missing hours remain explicit `NaN`.
   - **Processed (`data/processed/`)**:
     - `hourly_all.parquet`: Denormalized hourly station + weather join.
     - `daily.parquet`: Feature-engineered daily mart on PKT day boundaries with strict no-lookahead lags.

2. **Deterministic Primary Key Generation**:
   In `daily.parquet`, each station-day row is assigned an immutable, collision-resistant primary key:
   ```python
   record_id = hashlib.sha256(f"{station_slug}_{pkt_date}".encode("utf-8")).hexdigest()[:16]
   ```
   This guarantees idempotency, referential integrity for RAG agents, and stable joins across training/testing datasets.

3. **Time Boundary Isolation**:
   All timestamps stored across all Parquet tables remain timezone-aware UTC (`UTC`). The PKT date column is computed strictly as:
   ```python
   pkt_date = (timestamp_utc + pd.Timedelta(hours=5)).dt.date
   ```

4. **Audit Trail**:
   A root-level `manifest.csv` computes SHA-256 digests and row statistics directly from physical files on disk upon pipeline completion.

## Consequences
- Downstream models can consume `daily.parquet` directly without risk of future data leakage.
- All transformations are verifiable, reproducible, and easily wrapped into Prefect task decorators.
