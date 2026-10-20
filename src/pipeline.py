"""
End-to-End Air Quality Data Warehouse Pipeline Orchestrator.
Exposes modular steps for:
- discover: Station discovery and mapping (config/stations.yaml)
- fetch: OpenAQ + Open-Meteo incremental data acquisition
- verify_integrity: Raw data SHA-256 validation against manifest.csv
- clean: Timestamp dedupe, regular grid reindexing, quality validation, quality_log.csv
- process: Hourly station+weather join (hourly_all.parquet) and daily mart (daily.parquet)
- manifest: SHA-256 and metadata audit ledger (manifest.csv)
- status: Status JSON generation (status/run_status.json)
"""
import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from src.discover_stations import discover_and_build_config
from src.fetch_openaq import fetch_all_stations
from src.fetch_weather import fetch_weather
from src.clean import clean_all
from src.process import process_all
from src.manifest import generate_manifest, verify_raw_integrity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("pipeline")

STATUS_DIR = Path("status")
STATUS_FILE = STATUS_DIR / "run_status.json"


def write_run_status(
    openaq_results: Dict[str, Any],
    weather_files: List[Path],
    failed_stations: List[str],
    has_warnings: bool
) -> Path:
    """Write run status summary to status/run_status.json for dashboard ingestion."""
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc).isoformat()

    status_data = {
        "last_run_timestamp_utc": now_utc,
        "pipeline_status": "completed_with_warnings" if has_warnings else "completed_successfully",
        "has_warnings": has_warnings,
        "failed_stations": failed_stations,
        "sources": {
            "openaq": {
                "status": "partial_failures" if failed_stations else "healthy",
                "stations_total": len(openaq_results.get("station_results", {})),
                "stations_failed": len(failed_stations),
                "station_status": {
                    slug: {
                        "status": details.get("status"),
                        "error": details.get("error"),
                        "files_generated": len(details.get("saved_files", []))
                    }
                    for slug, details in openaq_results.get("station_results", {}).items()
                }
            },
            "open_meteo": {
                "status": "healthy" if weather_files or Path("data/cleaned/weather_cleaned.parquet").exists() else "warning",
                "weather_files_generated": len(weather_files),
                "weather_cleaned_exists": Path("data/cleaned/weather_cleaned.parquet").exists()
            }
        }
    }

    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)

    logger.info(f"Wrote run status summary to {STATUS_FILE}")
    return STATUS_FILE


def run_pipeline() -> bool:
    """
    Execute end-to-end data warehouse pipeline.
    Returns True if completed completely clean, or False if completed with warnings.
    """
    logger.info("Starting Air Quality Data Warehouse Pipeline (HackInsight 2026 - H4krz)...")
    warnings_list = []

    # Step 1: Discovery if not present
    config_file = Path("config/stations.yaml")
    if not config_file.exists():
        logger.info("=== STEP 1: STATION DISCOVERY ===")
        discover_and_build_config()

    # Step 2: Incremental Ingestion
    logger.info("=== STEP 2: INCREMENTAL DATA ACQUISITION ===")
    logger.info("--- 2A: Fetching OpenAQ v3 hourly observations ---")
    openaq_fetch_res = fetch_all_stations()
    failed_stations = openaq_fetch_res.get("failed_stations", [])
    if failed_stations:
        warnings_list.append(f"OpenAQ stations failed: {', '.join(failed_stations)}")

    logger.info("--- 2B: Fetching Open-Meteo historical and recent weather ---")
    weather_files = fetch_weather()

    # Step 3: Raw Data Integrity Verification against manifest.csv
    logger.info("=== STEP 3: PRE-CLEAN RAW INTEGRITY CHECK ===")
    verify_raw_integrity()

    # Step 4: Cleaning & Validation Layer
    logger.info("=== STEP 4: CLEANING & VALIDATION LAYER ===")
    clean_all()

    # Step 5: Processed Mart Layer
    logger.info("=== STEP 5: PROCESSED LAYER & DAILY MART ===")
    process_all()

    # Step 6: Manifest Generation
    logger.info("=== STEP 6: MANIFEST & INTEGRITY AUDIT ===")
    generate_manifest()

    # Step 7: Quality checks + short summary (guide ch.5, make data step 5)
    logger.info("=== STEP 7: DATA QUALITY AGENT CHECKS ===")
    try:
        import pandas as pd
        from src.dq_agent import run_dq_agent
        from src.prefect_pipeline import to_dq_contract

        hourly = pd.read_parquet("data/processed/hourly_all.parquet")
        _, dq_status = run_dq_agent(
            to_dq_contract(hourly),
            log_path="logs/dq_log.csv",
            status_path="logs/dq_status.json",
        )
        print(
            f"\nDQ SUMMARY: level={dq_status.get('level')} "
            f"rows={len(hourly)} valid={dq_status.get('valid_unimputed_rows')} "
            f"flagged={dq_status.get('flagged_rows')} imputed={dq_status.get('imputed_rows')}"
        )
        for reason in dq_status.get("reasons", []):
            print(f"  - {reason}")
        if dq_status.get("level") != "OK":
            warnings_list.append(f"DQ level {dq_status.get('level')}")
    except Exception as e:
        logger.error(f"Data Quality checks failed to run: {e}")
        warnings_list.append(f"DQ checks error: {e}")

    # Step 8: Status File
    has_warnings = len(warnings_list) > 0
    write_run_status(
        openaq_results=openaq_fetch_res,
        weather_files=weather_files,
        failed_stations=failed_stations,
        has_warnings=has_warnings
    )

    if has_warnings:
        logger.warning(
            f"Pipeline execution completed with warnings! Warning summary: {warnings_list}"
        )
        return False
    else:
        logger.info("Pipeline execution successfully completed with no warnings!")
        return True


def main():
    try:
        success = run_pipeline()
        if not success:
            logger.info("Pipeline exited with warnings reported.")
    except Exception as e:
        logger.error(f"Pipeline execution halted due to fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
