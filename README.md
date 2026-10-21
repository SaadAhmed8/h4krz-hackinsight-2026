# Lahore Air Quality Data Warehouse & Decision System (HackInsight 2026 - Team H4krz)

A robust, idempotent, and reproducible end-to-end data platform for acquiring, validating, forecasting, and querying hourly air quality (PM2.5) and ERA5 meteorological data for Lahore, Pakistan. Built for the HackInsight 2026 Hackathon (Data-to-Decision, Air Quality track).

---

## 1. Repository File Tree

```text
h4krz-hackinsight-2026/
├── .env.example
├── .gitattributes
├── .gitignore
├── AI_Use_Log.md
├── DATASET_DECLARATION.md
├── GLOSSARY.md
├── Makefile
├── README.md
├── REPORT.md
├── Summary.pdf
├── app.py
├── config/
│   ├── exclusions.yaml
│   ├── licence_evidence.csv
│   └── stations.yaml
├── data/
│   ├── cleaned/
│   │   ├── quality_log.csv
│   │   ├── station_allama_iqbal_town.parquet
│   │   ├── station_college_road.parquet
│   │   ├── station_forman_christian_college.parquet
│   │   ├── station_hbfc_society.parquet
│   │   ├── station_model_town.parquet
│   │   ├── station_pak_arab.parquet
│   │   ├── station_sandha_road.parquet
│   │   ├── station_trinity_school.parquet
│   │   ├── stations_hourly_dq.parquet
│   │   ├── weather_cleaned.parquet
│   │   └── weather_daily.parquet
│   ├── external/
│   │   ├── rag_sources.json
│   │   └── sources/
│   │       ├── epd-punjab-aqi-forecasting-advisories.pdf
│   │       ├── epd-punjab-aqi-forecasting-advisories.txt
│   │       ├── epd-punjab-general-public-advice.pdf
│   │       ├── epd-punjab-general-public-advice.txt
│   │       ├── who-global-air-quality-guidelines-2021.pdf
│   │       └── who-global-air-quality-guidelines-2021.txt
│   ├── processed/
│   │   ├── daily.parquet
│   │   ├── daily_station_table.csv
│   │   ├── daily_station_table.parquet
│   │   ├── hourly_all.parquet
│   │   ├── persistence_baseline_test_predictions.csv
│   │   ├── pm25_hist_gradient_boosting_test_predictions.csv
│   │   ├── predictions.csv
│   │   └── predictions.parquet
│   └── warehouse.duckdb
├── dataset_proposal.pdf
├── docs/
│   ├── adr/
│   │   └── 0001-warehouse-architecture-and-keys.md
│   └── evidence/
│       └── licences/
│           └── README.md
├── logs/
│   ├── dq_log.csv
│   ├── dq_status.json
│   └── prefect_runs.csv
├── manifest.csv
├── pytest.ini
├── reports/
│   ├── model_errors_by_group.csv
│   ├── monthly_validity.csv
│   ├── optimization_log.csv
│   ├── persistence_baseline_metrics.json
│   ├── pm25_hist_gradient_boosting_metrics.json
│   └── station_validity.csv
├── requirements.txt
├── run_data.ps1
├── scripts/
│   └── generate_summary_pdf.py
├── src/
│   ├── clean.py
│   ├── discover_stations.py
│   ├── dq_agent.py
│   ├── dq_schema.py
│   ├── fetch_openaq.py
│   ├── fetch_weather.py
│   ├── manifest.py
│   ├── model.py
│   ├── pipeline.py
│   ├── prefect_pipeline.py
│   ├── process.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── answer.py
│   │   ├── evidence.py
│   │   ├── external_sources.py
│   │   └── retrieval.py
│   ├── report_validity.py
│   ├── utils.py
│   └── warehouse.py
├── status/
│   └── run_status.json
└── tests/
    ├── conftest.py
    ├── test_dq_agent.py
    ├── test_pipeline.py
    ├── test_rag_answer.py
    └── test_rag_evidence.py
```
*(Note: `data/raw/` containing immutable raw fetch evidence JSONs is tracked in git but omitted above for brevity).*

---

## 2. Core System Components

### A. Data Warehouse & Quality Agent (Chapters 4 & 6)
- **Three-Layer Architecture:** Raw JSON payloads (`data/raw/`), cleaned hourly regular grids (`data/cleaned/`), and daily feature marts (`data/processed/daily.parquet`), synchronized to DuckDB (`data/warehouse.duckdb`).
- **Data Quality Agent (`src/dq_agent.py`):** Automatically validates schemas via Pandera, logs decisions to `data/cleaned/quality_log.csv`, and issues non-fatal `WARN_STALE` alerts when sensors lag without stopping pipeline progress.
- **Statistical Rules:** Midnight-to-midnight PKT day definition (UTC+5), strict 18-of-24 valid hours completeness threshold, and deterministic 16-character SHA-256 primary keys (`record_id`).

### B. Predictive Model & Uncertainty (Chapters 7 & 8)
- **Declared Baseline:** Persistence model ($\hat{y}_{t+1} = y_t$, MAE: $13.593\ \mu\text{g/m}^3$).
- **Final Model:** Histogram Gradient Boosting Regressor (`HistGradientBoosting_ResidualDelta`) predicting the day-to-day residual change using past historical lags and cross-station spatial dynamics.
- **Test Performance:** Test MAE: $12.594\ \mu\text{g/m}^3$ on 453 test rows (**7.35% improvement** over baseline).  
  > **Target Status:** The declared $\ge 15\%$ improvement target is **NOT MET**. An earlier experiment showing 18.05% was discarded because it inadvertently used realized next-day weather features. The leak-free model achieves 7.35% improvement.
- **Uncertainty Intervals:** 10th and 90th percentile pinball loss regressors producing 80% prediction intervals with **76.8% empirical test coverage**.
- **Group Fairness:** Full disaggregated error audit across stations, smog seasons, and pollution tiers documented in [reports/model_errors_by_group.csv](reports/model_errors_by_group.csv).

### C. Insight Agent / RAG Intelligence (Chapter 9)
- **Deterministic Evidence Retrieval:** Hybrid BM25 retrieval over official policy documents (WHO 2021 Global Air Quality Guidelines and Punjab EPA Smog Action Plan) and daily gold records (`data/processed/daily.parquet`).
- **Audit Traceability:** Numerical claims cite exact gold table `record_id` primary keys.
- **Safe Abstention:** Safely abstains with `"I don't know based on the available evidence"` for ungrounded queries (e.g. traffic or crop yields).
- **Pakistan Impact:** Bilingual Urdu emergency health advisories (`اردو ترجمہ`) and official Punjab EPA school activity thresholds.

### D. Automated Hourly Pipeline (Prefect Orchestrator)
- **Schedule:** Automated orchestration running at minute `:05` past every hour (`src/prefect_pipeline.py`).
- **Execution Log:** Every run status, timestamp, and row count is recorded in [logs/prefect_runs.csv](logs/prefect_runs.csv).
- **Resilience:** Incremental fetch only downloads newly elapsed hours; skips upstream errors gracefully.

### E. Interactive Streamlit Dashboard (`app.py`)
- **Tab 1: Live Monitoring:** Data freshness badges (`🟢 FRESH` / `🟡 LATE`), dynamic Open-Meteo parquet age calculation, DQ agent audit log, Punjab EPA school thresholds, and Urdu translation toggle.
- **Tab 2: Model & Group Fairness:** Baseline vs. model metrics, target status, 80% uncertainty bounds, and fairness breakdowns across groups.
- **Tab 3: AI Smog & Policy Assistant:** Interactive evidence-grounded Q&A with verifiable citations and exact gold record IDs.

---

## 3. How to Run

### Environment Variables
Configure credentials in `.env` using only variable names (never commit secrets):
- `OPENAQ_API_KEY`: API key for OpenAQ v3 access (register free at explore.openaq.org).
- `RAG_LLM_PROVIDER`: Optional LLM provider (`gemini`, `openai`, `anthropic`, or `openai_compatible`). Default: `gemini`.
- `GEMINI_API_KEY`: API key if using Gemini provider.
- `OPENAI_API_KEY`: API key if using OpenAI provider fallback.
- `ANTHROPIC_API_KEY`: API key if using Anthropic provider fallback.
- `RAG_LLM_MODEL`: Optional model override (e.g. `gemini-2.5-flash`).
- `RAG_LLM_TIMEOUT`: Timeout in seconds for LLM calls (default: 30).
- `RAG_LLM_MAX_TOKENS`: Maximum output tokens (default: 1024).
- `RAG_LLM_TEMPERATURE`: Generation temperature (default: 0.0).

### Execution Commands

```bash
# 1. Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Run full warehouse pipeline (idempotent)
make data
# Or on Windows:
python -m src.pipeline

# 3. Run automated test suite (52 tests)
python -m pytest tests/

# 4. Launch Streamlit Dashboard
streamlit run app.py

# 5. Run single Prefect pipeline execution cycle
python -m src.prefect_pipeline --once
```

---

## 4. Known Limitations & Documented Exclusions

1. **IEEE Station Excluded:** Station `ieee_punjab_univ` has its owner recorded as `"unverified"` in OpenAQ v3 metadata. In compliance with the participant licensing policy, its raw data is retained in `data/raw/` for audit purposes but strictly excluded from `data/cleaned/` and `data/processed/`.
2. **Model Town Link Road Upstream Error:** Station `model_town_link_rd` was discovered at OpenAQ sensor `16034758`, but OpenAQ upstream servers return `HTTP 500 Internal Server Error`. The failure is documented in [config/exclusions.yaml](config/exclusions.yaml) and skipped without fabricating data.
3. **Trinity School Completeness:** Station `trinity_school` exhibits low temporal completeness (35.01% valid PKT days; 10 test set samples) due to prolonged upstream sensor downtime.
4. **Weakest Station Performance:** `sandha_road` exhibits the lowest model improvement (+1.7% MAE reduction; 10.98 vs 11.17 baseline) due to erratic local diurnal variance.
5. **Declared Target Not Met:** The declared $\ge 15\%$ improvement target is **not met**; the leak-free model achieves +7.35% MAE reduction ($12.594\ \mu\text{g/m}^3$ vs $13.593\ \mu\text{g/m}^3$).
6. **Hourly Scheduler Gap:** The live run log in `logs/prefect_runs.csv` contains an unedited historical gap between `2026-10-20T16:56:53Z` and `2026-10-20T20:59:29Z` reflecting local machine downtime.

---

## 5. Process Notes & Early Commit History

The repository was initiated on 19 October 2026. Per the Participant Guide, the suggested milestone for the dataset declaration and proposal was Monday 19 Oct 12:00 PM PKT. The initial proposal commits occurred on the evening of 19 Oct 2026; these timestamps are truthfully recorded below and preserved without modification:

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

## 6. Project Verification & External Links

- **Automated Test Suite:** 52 tests passing (`python -m pytest tests/`).
- **Hugging Face Space Live Demo:** TO CONFIRM BY TEAM
- **Demo Video Link:** TO CONFIRM BY TEAM
- **Audit & Governance Documentation:**
  - Complete data acquisition and station coverage audit: [REPORT.md](REPORT.md)
  - Dataset declaration & contract adherence: [DATASET_DECLARATION.md](DATASET_DECLARATION.md)
  - Full AI assistance log with verified commit hashes: [AI_Use_Log.md](AI_Use_Log.md)
  - Physical file hash ledger: [manifest.csv](manifest.csv)
