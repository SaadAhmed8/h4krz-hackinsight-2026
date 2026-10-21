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