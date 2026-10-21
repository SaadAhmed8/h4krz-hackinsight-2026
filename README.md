# Lahore Air Quality Data Warehouse & Decision System (HackInsight 2026 - Team H4krz)

[![Tests](https://img.shields.io/badge/pytest-57%20passed-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](requirements.txt)
[![Licence](https://img.shields.io/badge/licence-CC%20BY%204.0-green.svg)](docs/evidence/licences/)
[![Orchestration](https://img.shields.io/badge/orchestrator-Prefect%203.x-purple.svg)](logs/prefect_runs.csv)

A fully auditable, idempotent, and reproducible three-layer data warehouse, predictive modeling engine, automated hourly monitoring pipeline, and cited RAG decision intelligence system for Lahore, Pakistan. Built for the **HackInsight 2026 Hackathon** (Air Quality track, Team H4krz).

---

## 📖 Guided Documentation Table of Contents
1. [Repository Structure & Artifacts](#1-repository-structure--artifacts)
2. [Architecture & Warehouse Foundations](#2-architecture--warehouse-foundations)
3. [Quickstart & Execution Guide](#3-quickstart--execution-guide)
4. [Automated Hourly Pipeline (Prefect Orchestration)](#4-automated-hourly-pipeline-prefect-orchestration)
5. [Live Monitoring & Decision Dashboard (Streamlit)](#5-live-monitoring--decision-dashboard-streamlit)
6. [Machine Learning & Group Fairness Audit](#6-machine-learning--group-fairness-audit)
7. [Insight Agent & Cited RAG Assistant](#7-insight-agent--cited-rag-assistant)
8. [Acceptance Criteria, Limits & Process Notes](#8-acceptance-criteria-limits--process-notes)
9. [Submission & Verification Deliverables](#9-submission--verification-deliverables)

---

## 1. Repository Structure & Artifacts

```text
h4krz-hackinsight-2026/
├── .env.example                                  # Template for API credentials & RAG settings
├── .gitattributes                                # Line endings & binary track configuration
├── .gitignore                                    # Git exclusion rules
├── AI_Use_Log.md                                 # Complete AI assistance log with verified commit hashes
├── DATASET_DECLARATION.md                        # Dataset contract, target decisions & volume analysis
├── GLOSSARY.md                                   # Domain glossary & ubiquitous vocabulary
├── Makefile                                      # High-level pipeline & test automation commands
├── README.md                                     # Main guided repository documentation
├── REPORT.md                                     # Exhaustive data acquisition & station coverage report
├── Summary.pdf                                   # 1-page executive summary for hackathon judges
├── app.py                                        # 3-Tab interactive Streamlit decision dashboard
├── check_summary.py                              # Automated validator ensuring Summary.pdf numerical honesty
├── export_prefect_runs.py                        # Prefect database inspector & run exporter
├── manifest.csv                                  # Audit ledger tracking SHA-256 hashes of all physical files
├── pytest.ini                                    # Pytest configuration
├── dataset_proposal.pdf                          # Original dataset proposal deliverable
├── requirements.txt                              # Pinned Python package dependencies
├── run_data.ps1                                  # Windows PowerShell pipeline execution script
├── verify_committed.py                           # Audit script checking raw files against git HEAD & manifest
├── config/
│   ├── exclusions.yaml                           # Excluded stations & documented upstream failure reasons
│   ├── licence_evidence.csv                      # Station-by-station licensing ledger & verification metadata
│   └── stations.yaml                             # Discovered station registry, location/sensor IDs & metadata
├── data/
│   ├── raw/                                      # Immutable raw JSON files (OpenAQ v3 & Open-Meteo ERA5)
│   ├── cleaned/                                  # Cleaned hourly Parquet series per station + quality_log.csv
│   │   ├── quality_log.csv                       # Data Quality Agent actions ledger (unit, fill, flag)
│   │   ├── station_*.parquet                     # Regular 1-hour UTC series for 8 verified stations
│   │   ├── stations_hourly_dq.parquet            # Consolidated multi-station hourly table
│   │   ├── weather_cleaned.parquet               # Open-Meteo hourly meteorological observations
│   │   └── weather_daily.parquet                 # Aggregated daily meteorological features
│   ├── external/                                 # Official RAG reference texts & JSON metadata
│   │   ├── rag_sources.json                      # Reference index of official domain guidance
│   │   └── sources/                              # WHO 2021 Guidelines & Punjab EPA Smog Action Plan PDFs/texts
│   ├── processed/                                # Golden processed marts & model evaluation predictions
│   │   ├── daily.parquet                         # Gold daily mart (PKT midnight-to-midnight, 18/24 rule)
│   │   ├── daily_station_table.csv/.parquet      # Flattened station-day feature table
│   │   ├── hourly_all.parquet                    # Joined air quality and meteorological hourly table
│   │   ├── persistence_baseline_test_predictions.csv
│   │   ├── pm25_hist_gradient_boosting_test_predictions.csv
│   │   └── predictions.csv/.parquet              # Test set predictions with 80% uncertainty bounds
│   └── warehouse.duckdb                          # Embedded DuckDB database synchronized from Parquet marts
├── docs/
│   ├── adr/0001-warehouse-architecture-and-keys.md
│   └── evidence/licences/                        # Collected raw OpenAQ location JSON licence evidence
├── logs/
│   ├── dq_log.csv                                # Step-by-step decision audit from Data Quality Agent
│   ├── dq_status.json                            # Latest runtime DQ agent assessment & staleness state
│   └── prefect_runs.csv                          # 24-hour hourly pipeline execution log with status codes
├── reports/
│   ├── model_errors_by_group.csv                 # Fairness audit across stations, seasons & pollution tiers
│   ├── monthly_validity.csv                      # Month-by-month completeness percentages
│   ├── optimization_log.csv                      # 3-iteration modeling log comparing candidates
│   ├── persistence_baseline_metrics.json         # Evaluation metrics for declared persistence baseline
│   ├── pm25_hist_gradient_boosting_metrics.json  # Final model test/validation metrics & data splits
│   └── station_validity.csv                      # Station completeness, valid days & missing gap analysis
├── scripts/
│   ├── build_proposal_pdf.py                     # Script compiling dataset_proposal.pdf
│   ├── build_space_bundle.py                     # Bundler for Hugging Face Space deployment
│   ├── export_prefect_runs.py                    # Official Prefect flow history exporter
│   ├── generate_summary_pdf.py                   # Script compiling 1-page Summary.pdf from live artifacts
│   └── sync_to_space.py                          # Hugging Face Space synchronization utility
├── src/
│   ├── clean.py                                  # Reindexing to regular 1-hour grid & anomaly handling
│   ├── collect_licence_evidence.py               # Automated OpenAQ location API licence fetcher
│   ├── discover_stations.py                      # OpenAQ v3 station & sensor discovery
│   ├── dq_agent.py                               # Autonomous Data Quality Agent
│   ├── dq_schema.py                              # Pandera contract definitions
│   ├── fetch_openaq.py                           # Incremental OpenAQ v3 hourly ingestion
│   ├── fetch_weather.py                          # Incremental Open-Meteo ERA5 hourly ingestion
│   ├── manifest.py                               # Physical file hash ledger & integrity verification
│   ├── model.py                                  # Leak-free HistGradientBoosting & pinball loss quantiles
│   ├── pipeline.py                               # Sequential warehouse pipeline orchestrator
│   ├── prefect_pipeline.py                       # Automated Prefect hourly scheduled flow
│   ├── process.py                                # Hourly merge, PKT day boundaries & lag feature creation
│   ├── report_validity.py                        # Station completeness & validity reporting
│   ├── utils.py                                  # Key loading, exponential backoff retries & logging
│   ├── warehouse.py                              # DuckDB analytical view creation
│   └── rag/                                      # Cited RAG assistant package
│       ├── __init__.py                           # Exported retrieval and generation functions
│       ├── answer.py                             # Multi-provider LLM answer synthesis with citations
│       ├── dashboard_report.py                   # Deterministic gold-table report generator
│       ├── evidence.py                           # Text chunking, indexing & schema models
│       ├── external_sources.py                   # Parsing of WHO & Punjab EPA policy guidelines
│       └── retrieval.py                          # Deterministic BM25 evidence retrieval engine
├── status/
│   └── run_status.json                           # Pipeline execution timestamps & source health status
└── tests/
    ├── conftest.py                               # Shared fixtures & test data
    ├── test_dashboard_report.py                  # Verification of deterministic RAG reports
    ├── test_dq_agent.py                          # Pandera validation & DQ rule test suite
    ├── test_pipeline.py                          # PKT day boundaries, 18/24 rule & lag isolation tests
    ├── test_rag_answer.py                        # LLM provider fallbacks & citation checks
    └── test_rag_evidence.py                      # Gold record row_id retrieval verification
```

---

## 2. Architecture & Warehouse Foundations

### Core Design Principles
1. **Three-Layer Warehouse:**
   - **Raw (`data/raw/`):** Immutable raw JSON payloads fetched from OpenAQ v3 and Open-Meteo ERA5 APIs.
   - **Cleaned (`data/cleaned/`):** Station series standardized to a strict 1-hour UTC grid. Missing hours are explicitly retained as `NaN`. Unit standardizations and anomalies are logged to `quality_log.csv`.
   - **Processed (`data/processed/`):** Feature-engineered `daily.parquet` gold mart aligned with meteorological variables, strictly avoiding lookahead bias.
2. **Strict Time Rules:**
   - **PKT Day Boundary:** A day runs midnight-to-midnight Pakistan Standard Time (PKT, UTC+5).
     $$\text{PKT Date} = \text{Date of } (T_{\text{UTC}} + 5\text{ hours})$$
   - **18-of-24 Completeness Rule:** A station-day is valid if and only if at least 18 out of 24 hourly readings are present. Otherwise, the daily mean is `NaN` and flagged `insufficient_hours`.
   - **Deterministic Primary Keys:** Every row in `daily.parquet` has a reproducible 16-character SHA-256 identifier:
     $$\text{record\_id} = \text{sha256}(\text{station\_slug} + \text{"\_"} + \text{pkt\_date})[:16]$$
3. **DuckDB Integration:** Cleaned and processed marts are registered as queryable analytical tables in `data/warehouse.duckdb`.

---

## 3. Quickstart & Execution Guide

### Prerequisites
- Python 3.11+
- Free OpenAQ API key from [explore.openaq.org/register](https://explore.openaq.org/register)

### Setup Environment
```bash
# 1. Clone repository
git clone https://github.com/SaadAhmed8/h4krz-hackinsight-2026.git
cd h4krz-hackinsight-2026

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# 3. Install pinned dependencies
pip install -r requirements.txt

# 4. Configure environment credentials
cp .env.example .env
# Open .env and insert your OPENAQ_API_KEY (and optional LLM provider keys)
```

### Environment Variables (.env)
| Variable Name | Description | Default / Options |
| :--- | :--- | :--- |
| `OPENAQ_API_KEY` | OpenAQ v3 API authentication key | *Required for live ingestion* |
| `RAG_LLM_PROVIDER` | LLM backend for RAG Assistant | `gemini` (default), `openai`, `anthropic`, `openai_compatible` |
| `GEMINI_API_KEY` | Google Gemini API Key | *Required if provider is gemini* |
| `OPENAI_API_KEY` | OpenAI API Key | *Optional fallback* |
| `ANTHROPIC_API_KEY` | Anthropic API Key | *Optional fallback* |
| `RAG_LLM_MODEL` | Specific LLM model identifier | `gemini-2.5-flash` |
| `RAG_LLM_TIMEOUT` | Network timeout for RAG synthesis | `30` (seconds) |
| `RAG_LLM_TEMPERATURE` | Model temperature (deterministic generation) | `0.0` |

### Pipeline Commands (Makefile & Python)
```bash
# Execute complete end-to-end acquisition & warehouse build
make data
# Or directly via Python:
python -m src.pipeline

# Run full automated test suite (57 tests)
make test
# Or directly via pytest:
python -m pytest -q

# Run station discovery
make discover

# Collect raw licence evidence JSONs from OpenAQ location APIs
make licence-evidence

# Export official Prefect flow run history
make export-prefect
```

---

## 4. Automated Hourly Pipeline (Prefect Orchestration)

The automated production pipeline runs under **Prefect 3.x** (`src/prefect_pipeline.py`), designed to execute at minute `:05` past each hour.

```bash
# Run a single immediate execution cycle:
python -m src.prefect_pipeline --once

# Run continuous background scheduler loop:
python -m src.prefect_pipeline
```

### Key Orchestration Features:
- **Incremental Resumption:** Inspects the latest stored timestamp per sensor and downloads only newly elapsed hours. Redundant network traffic is zero.
- **Contract Error Handling:** Data Quality Agent contract failures fail fast without retry, preventing pipeline corruption.
- **Staleness Resilience:** If an individual sensor lags upstream, the DQ Agent flags it as `WARN_STALE` and allows the pipeline to continue.
- **Audit Logging:** Every hourly cycle logs its execution timestamp, pipeline status (`SUCCESS` / `FAILED_DQ`), and row counts directly into `logs/prefect_runs.csv`.

---

## 5. Live Monitoring & Decision Dashboard (Streamlit)

Launch the decision portal locally:
```bash
streamlit run app.py
```

### Dashboard Features:
1. **Top Live Health Banner (Chapter 10):**
   - Individual freshness indicators for **OpenAQ** and **Open-Meteo** (triggers `🟡 LATE` if the newest `fetched_at_utc` in `manifest.csv` is older than 2.0 hours).
   - Real-time **Data Quality Agent** status badge (`🟢 OK`, `🟡 WARN`, `🔴 FAIL`).
   - Time and status of the last successful automated pipeline run.
2. **Tab 1: Live Monitoring & Quality Audit:**
   - Punjab EPA Smog Action Plan outdoor school activity directives (<50 Satisfactory, 50-150 Moderate, 150-250 Outdoor sports suspended, >250 Online classes/closure).
   - Bilingual Urdu emergency guidance toggle (`اردو ترجمہ`).
   - Interactive historical PM2.5 time-series graphs per station.
   - Expandable decision logs from `logs/dq_log.csv` and `logs/prefect_runs.csv`.
3. **Tab 2: Model & Group Fairness:**
   - Side-by-side metric comparison of the Final Model vs. Persistence Baseline.
   - 80% prediction uncertainty interval audit.
   - Disaggregated group fairness evaluations across geographical stations, smog seasons (Oct-Feb vs Mar-Sep), and pollution severity tiers.
4. **Tab 3: AI Smog & Policy Assistant:**
   - Evidence-grounded question-answering with exact gold record IDs (`daily.parquet` `record_id`).
   - Deterministic citations referencing WHO 2021 guidelines and Punjab EPA advisories.
   - Out-of-scope query guardrails with safe abstention ("❌ I don't know based on the available evidence").

---

## 6. Machine Learning & Group Fairness Audit

### Model Formulation (Leak-Free Residual Delta)
- **Problem Statement:** Forecast next-day average PM2.5 concentration ($y_{t+1}$) for each station.
- **Baseline Model:** Persistence baseline ($\hat{y}_{t+1} = y_t$, MAE: $13.593\ \mu\text{g/m}^3$).
- **Final Model:** Histogram Gradient Boosting Regressor (`HistGradientBoosting_ResidualDelta`) trained to predict the residual change $\Delta y = y_{t+1} - y_t$ using only historical features (same-day lags, rolling statistics, cross-station dynamics, and prior-day weather).
- **Leakage Prevention:** Next-day weather leads and lookahead features were strictly eliminated. Candidates were chosen strictly by validation set MAE.

### Verified Performance Summary
| Metric | Persistence Baseline | HistGradientBoosting Model | Relative Improvement |
| :--- | :---: | :---: | :---: |
| **Test Set MAE** | $13.593\ \mu\text{g/m}^3$ | **$12.594\ \mu\text{g/m}^3$** | **+7.35%** |
| **Test Set RMSE** | $17.774\ \mu\text{g/m}^3$ | **$16.354\ \mu\text{g/m}^3$** | **+7.99%** |
| **80% Uncertainty Coverage** | — | **76.8%** | *Pinball loss $10^{th}$ & $90^{th}$ quantiles* |
| **Test Sample Count** | 453 station-days | 453 station-days | *76 unique test dates* |

> ⚠️ **Declared Target Status:** The declared $\ge 15\%$ improvement target is **NOT MET** (+7.35% actual gain). An earlier reported 18.05% result was discarded because it inadvertently used realized next-day weather features. The verified leak-free model achieves 7.35% improvement.

### Group Fairness Breakdown (`reports/model_errors_by_group.csv`)
- **Seasons:**
  - Non-Smog Season (Mar-Sep): Model MAE $12.13\ \mu\text{g/m}^3$ (+6.0% gain, 330 samples)
  - Smog Season (Oct-Feb): Model MAE $13.85\ \mu\text{g/m}^3$ (+10.4% gain, 123 samples — highest gain where smog warning matters most)
- **Stations:**
  - Strongest gain: `trinity_school` (11.47 MAE, +22.8% gain)
  - Weakest station by model change: `sandha_road` (10.98 MAE, +1.7% gain) due to localized micro-climate fluctuations.

---

## 7. Insight Agent & Cited RAG Assistant

The RAG Assistant combines deterministic semantic evidence retrieval with grounded LLM generation:
1. **Gold Table Grounding:** Numeric air quality claims are mapped directly to primary keys (`record_id`) in `daily.parquet`.
2. **Authoritative Citations:** Answers ground health recommendations in the WHO 2021 Global Air Quality Guidelines and Punjab EPA Smog Action Plan.
3. **Safe Abstention:** When posed out-of-scope or ungrounded questions (e.g. traffic congestion, industrial output), the system explicitly refuses:
   `"❌ I don't know based on the available evidence. The system only includes air quality observations and official health guidelines."`
4. **Deterministic Fallback:** If no external LLM API key is configured, the system deterministically compiles structured gold-table reports with exact row IDs.

---

## 8. Acceptance Criteria, Limits & Process Notes

### Known Limitations & Documented Exclusions
1. **IEEE Station Excluded:** Station `ieee_punjab_univ` has its owner recorded as `"unverified"` in OpenAQ v3 metadata. In compliance with licensing policies, raw data is archived in `data/raw/` for audit purposes but strictly excluded from cleaned and processed marts.
2. **Model Town Link Road Upstream Error:** Station `model_town_link_rd` sensor (`16034758`) returns `HTTP 500 Internal Server Error` upstream from OpenAQ servers. Documented in `config/exclusions.yaml` and skipped without fabricating data.
3. **Trinity School Completeness:** `trinity_school` exhibits low completeness (35.01% valid PKT days; 10 test samples) due to prolonged upstream sensor downtime.
4. **Hourly Scheduler Gap:** The live run log in `logs/prefect_runs.csv` contains an unedited historical gap between `2026-10-20T16:56:53Z` and `2026-10-20T20:59:29Z` reflecting local machine downtime.
5. **Licence Evidence:** Raw JSON location metadata files are collected in `docs/evidence/licences/openaq_*.json`. Physical browser screenshots remain pending.

### Process Notes & Early Commit History
The repository was initiated on 19 October 2026. Per the Participant Guide, the suggested milestone for the dataset declaration was Monday 19 Oct 12:00 PM PKT. The initial proposal commits were recorded on the evening of 19 Oct 2026; these timestamps are truthfully declared below and preserved without modification:

| Hash | Timestamp (PKT) | Commit Subject |
| :--- | :--- | :--- |
| `cfea4ea` | 2026-10-19T20:19:44+05:00 | Initial commit |
| `4187eb0` | 2026-10-19T20:25:46+05:00 | Delete README.md |
| `dce3b42` | 2026-10-19T20:21:14+05:00 | Add dataset declaration |
| `40eb664` | 2026-10-19T20:31:36+05:00 | Add dataset declaration with corrected volume estimate |
| `b5cb96b` | 2026-10-19T20:53:42+05:00 | Data proposal |
| `338cd28` | 2026-10-19T20:59:12+05:00 | Data proposal |
| `83120e1` | 2026-10-19T23:41:14+05:00 | feat: robust air quality warehouse with integrity audits, failure handling, and validity reporting |
| `d32b481` | 2026-10-20T00:10:23+05:00 | fix: resolve test isolation bugs and upgrade immutability guard |

---

## 9. Submission & Verification Deliverables

- **Automated Test Suite:** 57 tests passing (`python -m pytest -q`).
- **Live Decision Dashboard (Hugging Face Space):** [https://huggingface.co/spaces/hasanshahir/lahore-air-quality-decision-system](https://huggingface.co/spaces/hasanshahir/lahore-air-quality-decision-system) 
- **Demo Video:**https://youtu.be/uSY8lgxd3pc
- **Executive Summary:** Exactly 1-page PDF compiled from live repo artifacts ([Summary.pdf](Summary.pdf)).
- **Audit Ledgers:**
  - Complete acquisition & warehouse report: [REPORT.md](REPORT.md)
  - Dataset declaration & contract: [DATASET_DECLARATION.md](DATASET_DECLARATION.md)
  - AI assistance log with verified commits: [AI_Use_Log.md](AI_Use_Log.md)
  - Physical file hash integrity ledger: [manifest.csv](manifest.csv)

## 👥 Team Members & Roles

| Name | Role | Responsibilities & Contributions |
| :--- | :--- | :--- |
| **Saad Ahmed** | **Team Lead / Lead Data & Software Engineer** | Data warehouse design & construction (DuckDB/Parquet layers), repository architecture, GitHub release & tagging (`v1.0-final`), and system integration. |
| **Hasan Shahir** | **MLOps & Pipeline Engineer** | Prefect hourly data orchestration pipeline, OpenAQ & Open-Meteo integrations, and Hugging Face deployment. |
| **Noman Tariq** | **ML & RAG Architecture Lead** | `HistGradientBoosting` PM2.5 forecasting model, uncertainty interval bounds, and cited RAG policy assistant. |
| **Arbish** | **Documentation & Compliance Specialist** | Manifest tracking, `AI_Use_Log.md` compliance, data quality audits, and submission deliverables. |
