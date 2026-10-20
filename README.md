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

## Running the Automated Pipeline & Dashboard

### 1. Automated Hourly Pipeline (Prefect)
The hourly pipeline runs automatically on its own at `:05` past each hour:
```bash
# Run a single immediate cycle (or verify pipeline execution):
python -m src.prefect_pipeline --once

# Run continuous hourly scheduler loop (triggers at minute :05 past every hour):
python -m src.prefect_pipeline
```
All pipeline runs, statuses (`SUCCESS`), timestamps, and row counts are recorded in [logs/prefect_runs.csv](logs/prefect_runs.csv).

### 2. Streamlit Live Monitoring & Decision Dashboard
Launch the interactive dashboard:
```bash
streamlit run app.py
```
The dashboard features three tabs:
- **📊 Live Monitoring:** Data freshness badges (`🟢 FRESH` / `🟡 LATE`), latest Data Quality Agent status (`logs/dq_status.json`), Prefect execution history, EPA Punjab Smog Action Plan school outdoor safety thresholds, and an Urdu language toggle (`اردو ترجمہ`).
- **📈 Model & Group Fairness:** Declared persistence baseline vs. HistGradientBoosting model (18.05% MAE reduction), 80% multi-quantile uncertainty intervals, and group fairness breakdown across stations, seasons, and pollution tiers.
- **🤖 AI Smog & Policy Assistant (RAG):** Evidence-grounded answers citing WHO 2021 guidelines and EPA Punjab advisories. Numerical observations cite exact gold table row IDs (`daily.parquet` / `warehouse.duckdb`). Includes "I don't know" out-of-scope testing and emergency health disclaimers.

---

## Machine Learning & Group Fairness (Chapters 7 & 8)

- **Declared Baseline:** Persistence baseline ($\hat{y}_{t+1} = y_t$, MAE: $13.593\ \mu\text{g/m}^3$).
- **Final Model:** Histogram Gradient Boosting Regressor with weather forecast leads and cross-station dynamics (MAE: $11.139\ \mu\text{g/m}^3$, **18.05% improvement**).
- **Uncertainty Bounds:** $10^{th}$ and $90^{th}$ percentile pinball loss regressors producing reliable 80% prediction intervals.
- **Group Fairness:** Full error audit across stations, smog seasons (Oct-Feb vs Mar-Sep), and pollution tiers documented in [reports/model_errors_by_group.csv](reports/model_errors_by_group.csv).

---

## Running the Test Suite

Run the full automated test suite (52 tests covering pipeline, DQ agent, RAG evidence retrieval, and RAG answer generation):
```bash
python -m pytest tests/
```
Output:
```text
tests/test_dq_agent.py ...........                                       [ 21%]
tests/test_pipeline.py .......                                           [ 34%]
tests/test_rag_answer.py ....................                            [ 73%]
tests/test_rag_evidence.py ..............                                [100%]
============================== 52 passed in 21.45s ==============================
```

---

## Data Summary & Attribution

- **OpenAQ v3 API:** Air quality observations provided under Creative Commons Attribution 4.0 International (CC BY 4.0).
- **Open-Meteo:** Historical weather reanalysis data provided by Open-Meteo.com under CC BY 4.0.
- **Licensing Compliance:** Station `ieee_punjab_univ` is strictly excluded from cleaned/processed layers due to unverified licensing.
- Detailed station metrics, coverage percentages, and validity counts are documented in [REPORT.md](REPORT.md).
- Dataset declaration and problem analysis are documented in [DATASET_DECLARATION.md](DATASET_DECLARATION.md).
- AI usage and human verification records are logged in [AI_Use_Log.md](AI_Use_Log.md).
