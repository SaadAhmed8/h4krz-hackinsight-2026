# Makefile for HackInsight 2026 - Air Quality Data Warehouse
# Platform agnostic execution: Works in Git Bash, WSL, GNU Make, or via `python -m src.pipeline` fallback

PYTHON ?= python

.PHONY: all data fetch clean process manifest warehouse discover test report clean-data licence-evidence export-prefect help

all: data

## licence-evidence: Query OpenAQ location APIs and collect raw JSON licence evidence
licence-evidence:
	$(PYTHON) -m src.collect_licence_evidence

## export-prefect: Export official Prefect flow run history for the 24h window (run after Wed 4 PM PKT)
export-prefect:
	$(PYTHON) scripts/export_prefect_runs.py

## data: Run full end-to-end data acquisition and warehouse pipeline (fetch -> verify -> clean -> process -> manifest -> warehouse -> status)
data:
	$(PYTHON) -m src.pipeline

## warehouse: Build or refresh data/warehouse.duckdb from processed layers
warehouse:
	$(PYTHON) -m src.warehouse

## discover: Discover Lahore stations and generate config/stations.yaml
discover:
	$(PYTHON) -m src.discover_stations

## fetch: Fetch OpenAQ and Open-Meteo incremental data into data/raw/
fetch:
	$(PYTHON) -m src.fetch_openaq
	$(PYTHON) -m src.fetch_weather

## clean: Validate, reindex and clean raw series into data/cleaned/
clean:
	$(PYTHON) -m src.clean

## process: Build hourly_all.parquet and daily.parquet in data/processed/
process:
	$(PYTHON) -m src.process

## manifest: Regenerate manifest.csv with SHA-256 digests and row counts
manifest:
	$(PYTHON) -m src.manifest

## report: Generate station_validity.csv and monthly_validity.csv
report:
	$(PYTHON) -m src.report_validity

## test: Run unit tests on PKT boundaries, 18/24 rule, lags, deterministic keys, and failure recovery
test:
	$(PYTHON) -m pytest tests/

## clean-data: Remove cleaned and processed artifacts (keeps data/raw/ intact)
clean-data:
	$(PYTHON) -c "import shutil, os; [shutil.rmtree(p, ignore_errors=True) for p in ['data/cleaned', 'data/processed', 'status', 'reports']]; [os.remove('manifest.csv') if os.path.exists('manifest.csv') else None]"

## help: Display available Makefile targets
help:
	@echo Available Makefile targets:
	@echo   make data        - Run full acquisition and warehouse pipeline
	@echo   make discover    - Discover stations and write config/stations.yaml
	@echo   make fetch       - Incrementally fetch raw OpenAQ and weather data
	@echo   make clean       - Clean and validate raw data into data/cleaned/
	@echo   make process     - Build hourly_all.parquet and daily.parquet
	@echo   make manifest    - Regenerate manifest.csv
	@echo   make report      - Compute true valid hours and station validity report
	@echo   make test        - Run automated pytest unit test suite
	@echo   make clean-data  - Reset cleaned/processed layers without deleting raw data
