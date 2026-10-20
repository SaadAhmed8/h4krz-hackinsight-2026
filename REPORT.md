# Air Quality Data Acquisition & Warehouse Report

**Event:** HackInsight 2026 (Data-to-Decision)  
**Track:** Air Quality  
**Team:** H4krz  
**Deliverable:** Data Acquisition and Warehouse  
**Generated At:** 2026-10-19T18:00:00Z  

---

## 1. Executive Summary

This report documents the end-to-end data acquisition and three-layer warehouse implementation for monitoring and forecasting next-day PM2.5 air pollution across Lahore, Pakistan.

- **Total Hourly Observations Stored (Cleaned Grid):** 98,272 hourly rows across stations
- **Total Valid PM2.5 Hourly Measurements:** 75,784 hourly rows
- **50,000+ Threshold Target:** **PASSED** (75,784 > 50,000 hourly rows)
- **Total Daily Mart Records (`daily.parquet`):** 4,101 station-days
- **Valid PKT Days ($\ge 18$ valid hours):** 3,005 days
- **Weather Observations (Open-Meteo ERA5):** 12,264 hourly records (2025-05-26 to 2026-10-18 UTC)
- **Licence Compliance:** 100% CC BY 4.0 compliant across all ingested sources

---

## 2. Station Inventory & Coverage Analysis

All 10 target stations were queried via OpenAQ API v3. 9 stations successfully returned complete hourly histories. One station (`Model Town Link Rd B LHE`) was successfully discovered and registered, but its sensor endpoint currently returns HTTP 500 upstream from OpenAQ's backend.

| Station Slug | Station Name | Provider | Owner | Licence | Date Range (UTC) | Hourly Grid | Valid PM2.5 | Completeness | Total Days | Valid PKT Days (>=18h) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `hbfc_society` | HBFC Society, DHA Phase 5 (Hussainy House) | AirGradient | The Urban Unit | CC BY 4.0 | 2025-05-26 to 2026-10-19 | 12,269 | 10,689 | 87.1% | 512 | 433 |
| `sandha_road` | Sandha Road | AirGradient | The Urban Unit | CC BY 4.0 | 2025-05-29 to 2026-10-19 | 12,202 | 8,846 | 72.5% | 509 | 318 |
| `model_town` | Model Town | AirGradient | The Urban Unit | CC BY 4.0 | 2025-05-30 to 2026-10-19 | 12,174 | 11,258 | 92.5% | 508 | 464 |
| `college_road` | College Road | AirGradient | The Urban Unit | CC BY 4.0 | 2025-06-02 to 2026-10-19 | 12,096 | 9,421 | 77.9% | 505 | 366 |
| `pak_arab` | Pak Arab | AirGradient | The Urban Unit | CC BY 4.0 | 2025-09-19 to 2026-10-19 | 9,498 | 6,948 | 73.2% | 396 | 283 |
| `ieee_punjab_univ` | IEEE, Punjab University, LHR | AirGradient | unverified | CC BY 4.0 | 2025-05-30 to 2026-10-19 | 12,179 | 10,185 | 83.6% | 508 | 407 |
| `allama_iqbal_town` | Allama Iqbal Town B LHE | Hawanama | PAQI | CC BY 4.0 | 2025-11-18 to 2026-10-19 | 8,043 | 5,020 | 62.4% | 336 | 191 |
| `forman_christian_college` | Forman Christian College & Chartered University | AirGradient | The Urban Unit | CC BY 4.0 | 2025-06-16 to 2026-10-19 | 11,768 | 10,583 | 89.9% | 491 | 426 |
| `trinity_school` | Trinity School Lahore | Hawanama | PAQI | CC BY 4.0 | 2025-11-18 to 2026-10-19 | 8,043 | 2,834 | 35.2% | 336 | 117 |
| `model_town_link_rd` | Model Town Link Rd B LHE | Hawanama | PAQI | CC BY 4.0 | N/A (Upstream 500) | 0 | 0 | 0.0% | 0 | 0 |
| **TOTAL** | — | — | — | — | — | **98,272** | **75,784** | **77.1%** | **4,101** | **3,005** |

### Discovery & Licence Notes
- **IEEE Punjab University:** As required by project specifications, IEEE station owner is unconfirmed and recorded strictly as `"unverified"` in both config and data marts.
- **Model Town Link Rd B LHE:** Discovered successfully at OpenAQ location ID `6318826` and sensor `16034758`. When queried, OpenAQ returns `HTTP 500 Internal Server Error` on both `/hours` and `/measurements` endpoints. The pipeline gracefully handles this without breaking, documents the upstream failure, and skips without fabricating data.
- **Licencing:** All stations provide data under CC BY 4.0. No non-standard licences were encountered.

---

## 3. Data Warehouse Architecture

### Layer 1: Raw Layer (`data/raw/`)
- 38 immutable JSON files stored directly upon fetch.
- Contains unaltered raw payloads from OpenAQ and Open-Meteo.
- Filenames include station slug, sensor parameter, and UTC fetch timestamps.

### Layer 2: Cleaned Layer (`data/cleaned/`)
- Standardized Parquet files (`station_{slug}.parquet` and `weather_cleaned.parquet`).
- Reindexed onto a complete 1-hour UTC regular grid spanning the active duration of each station. Missing hours are explicitly retained as `NaN`.
- Decisions tracked in `quality_log.csv`. Missing timestamp gaps logged: 9 fill actions totaling 22,488 missing hourly slots across stations.

### Layer 3: Processed Layer (`data/processed/`)
- `hourly_all.parquet`: Joined table of all 9 stations merged with hourly ERA5 weather on UTC hour (98,272 rows).
- `daily.parquet`: Feature-engineered daily mart on PKT day boundaries (UTC+5, midnight to midnight) with:
  - Deterministic 16-character SHA-256 primary key (`record_id`).
  - 18-of-24 rule enforcement (requires $\ge 18$ valid hours; otherwise mean is `NaN` and flagged `insufficient_hours`).
  - Strict no-lookahead historical lag features (`pm25_lag_1d`, `pm25_lag_2d`, `pm25_lag_7d_rolling_mean`).
  - Target variable: `target_next_day_pm25` (tomorrow's mean, strictly aligned to day $D+1$ if valid).

### Layer 4: Audit Ledger (`manifest.csv`)
- 50 rows recording every physical artifact in `data/raw/`, `data/cleaned/`, and `data/processed/`.
- Contains layer, path, source, station, provider, owner, licence, row counts, timestamp ranges, and SHA-256 digests.

---

## 4. Acceptance Criteria Verification

| Requirement | Status | Verification Evidence |
| :--- | :---: | :--- |
| `make data` / `python -m src.pipeline` | **PASS** | Completes end-to-end cleanly across all layers |
| Idempotency & Incremental Resume | **PASS** | Second run checks latest stored timestamp and downloads 0 new rows |
| manifest.csv Integrity | **PASS** | 50 physical files verified with SHA-256 digests and row bounds |
| quality_log.csv | **PASS** | Explains every fill/flag action taken |
| Automated Pytest Suite | **PASS** | 18 passed (`tests/test_pipeline.py`, `tests/test_dq_agent.py`), re-run 2026-10-20 |
| Total PM2.5 Hourly Rows > 50,000 | **PASS** | 75,784 valid hourly PM2.5 measurements acquired |
