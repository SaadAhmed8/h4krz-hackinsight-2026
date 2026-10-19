# Lahore Air Quality Data Warehouse (HackInsight 2026 - H4krz)

A robust, idempotent, and reproducible three-layer data warehouse for acquiring, cleaning, and processing hourly air quality (PM2.5) and ERA5 meteorological data for Lahore, Pakistan. Built for the HackInsight 2026 Hackathon (Data-to-Decision, Air Quality track).

---

## Architecture Overview

```text
h4krz-hackinsight-2026/
├── config/
│   └── stations.yaml         # Discovered Lahore stations, sensor IDs, provider & licence metadata
├── data/
│   ├── raw/                  # Immutable raw JSON files (OpenAQ + Open-Meteo ERA5)
│   ├── cleaned/              # Cleaned Parquet series per station + quality_log.csv
│   └── processed/            # hourly_all.parquet & daily.parquet mart
├── docs/
│   └── adr/                  # Architectural Decision Records (ADR 0001)
├── src/
│   ├── discover_stations.py  # OpenAQ v3 API station and sensor discovery
│   ├── fetch_openaq.py       # Incremental hourly OpenAQ data ingestion
│   ├── fetch_weather.py      # Incremental Open-Meteo ERA5 historical weather ingestion
│   ├── clean.py              # Cleaning, hourly regular grid reindexing & anomaly flagging
│   ├── process.py            # Hourly join & daily mart with 18/24 rule & no-lookahead lags
│   ├── manifest.py           # Integrity ledger & SHA-256 manifest generator
│   ├── pipeline.py           # End-to-end pipeline orchestrator
│   └── utils.py              # Key loader, exponential backoff HTTP retries & logging
├── tests/
│   └── test_pipeline.py      # Pytest suite (PKT day boundaries, 18/24 rule, lags, deterministic keys)
├── .agents/skills/           # Agent skills (domain-modeling, codebase-design, minimal-run-and-audit)
├── GLOSSARY.md               # Ubiquitous domain terminology and schema definitions
├── REPORT.md                 # Complete data acquisition and station coverage report
├── manifest.csv              # Audit evidence ledger with SHA-256 hashes for all files
├── Makefile                  # Pipeline automation targets
├── requirements.txt          # Pinned Python dependencies
└── .env.example              # Template for API credentials
```

---

## Quickstart

### 1. Prerequisites
- Python 3.11+
- An OpenAQ API key (register for free at [explore.openaq.org/register](https://explore.openaq.org/register))

### 2. Setup Environment
```bash
# Clone the repository
git clone <repo-url>
cd h4krz-hackinsight-2026

# Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and enter your key:
# OPENAQ_API_KEY=your_key_here
```

### 3. Run Pipeline (`make data`)
You can run the full pipeline end-to-end with a single command:

```bash
make data
```

> **Running on Windows:**
> - If `make` is installed (via Chocolatey `choco install make`, Git Bash, or WSL), `make data` will execute directly.
> - As a first-class alternative on Windows PowerShell/CMD, run:
>   ```powershell
>   python -m src.pipeline
>   ```
> Both commands run the exact same orchestrator.

### 4. Idempotency & Incremental Re-runs
Re-running `make data` or `python -m src.pipeline` is completely idempotent. The pipeline inspects the latest stored timestamp in `data/raw/` for each sensor and only downloads newly elapsed hours. When already up-to-date, zero redundant network data is fetched.

---

## Time Rules & Target Definition

1. **Storage Timestamps:** All persistent datetime fields are stored in **timezone-aware UTC** (`UTC`).
2. **PKT Day Definition:** A "day" runs midnight-to-midnight in Pakistan Standard Time (PKT, UTC+5, `Asia/Karachi`).
   $$\text{PKT Date} = \text{Date of } (T_{\text{UTC}} + 5\text{ hours})$$
   *(For example: `19:00 UTC` on Oct 19 belongs to the `2025-10-20` PKT day).*
3. **The 18-of-24 Rule:** A `(station, pkt_date)` daily aggregation is considered statistically valid if and only if at least 18 of its 24 hourly values exist. Otherwise, the daily mean is `NaN` and the row is flagged `"insufficient_hours"`.
4. **Deterministic Primary Keys:** In `daily.parquet`, each station-day row has a collision-resistant, reproducible identifier:
   $$\text{record\_id} = \text{sha256}(\text{slug} + \text{"\_"} + \text{pkt\_date})[:16]$$
5. **No Future Leakage:** All lag features (`pm25_lag_1d`, `pm25_lag_2d`, `pm25_lag_7d_rolling_mean`) strictly use prior days only.
6. **Next-Day Target:** For day $D$, `target_next_day_pm25` is the daily mean of day $D+1$ (assigned only if day $D+1$ is valid).

---

## Makefile Targets

| Target | Description |
| :--- | :--- |
| `make data` | Runs full acquisition and warehouse pipeline (fetch -> clean -> process -> manifest) |
| `make discover` | Discovers OpenAQ stations in Lahore and writes `config/stations.yaml` |
| `make fetch` | Incrementally downloads raw OpenAQ and weather data into `data/raw/` |
| `make clean` | Reindexes to regular hourly grid, validates values, and logs to `quality_log.csv` |
| `make process` | Joins stations with weather (`hourly_all.parquet`) and generates daily mart (`daily.parquet`) |
| `make manifest` | Recomputes SHA-256 hashes and row counts directly from physical files |
| `make test` | Executes unit tests covering PKT boundaries, 18/24 rule, lags, and deterministic keys |
| `make clean-data` | Resets cleaned and processed layers while keeping `data/raw/` immutable |

---

## Running Unit Tests

Run the test suite with pytest:
```bash
python -m pytest tests/
```
Output:
```text
tests/test_pipeline.py ....                                              [100%]
4 passed in 1.93s
```
All unit tests run on synthetic in-memory fixtures without requiring network access.

---

## Data Summary & Attribution

- **OpenAQ v3 API:** Air quality observations provided under Creative Commons Attribution 4.0 International (CC BY 4.0).
- **Open-Meteo:** Historical weather reanalysis data provided by Open-Meteo.com under CC BY 4.0.
- Detailed station metrics, coverage percentages, and validity counts are documented in [REPORT.md](file:///c:/Users/HP/h4krz-hackinsight-2026/REPORT.md).
