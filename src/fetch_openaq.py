"""
Fetch hourly air quality measurements from OpenAQ v3 API.
Idempotent and incremental: reads existing raw files, detects last stored timestamp,
and fetches only missing time ranges per sensor.

Robust Error Handling:
- Every station/sensor fetch ends with an explicit status: 'ok', 'up_to_date', or 'failed' (with error).
- Failed fetches write to temporary files and only rename on success (atomic write).
- Failures are recorded as flags in data/cleaned/quality_log.csv.
- Checks config/exclusions.yaml for stations with documented upstream outages.
"""
import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import yaml

from src.utils import get_openaq_api_key, safe_request

logger = logging.getLogger("fetch_openaq")

RAW_DIR = Path("data/raw")
CONFIG_PATH = Path("config/stations.yaml")
EXCLUSIONS_PATH = Path("config/exclusions.yaml")
QUALITY_LOG_PATH = Path("data/cleaned/quality_log.csv")


def load_stations_config(config_path: Path = CONFIG_PATH) -> List[Dict[str, Any]]:
    """Load discovered stations from YAML config."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at {config_path}. Run discovery first.")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("stations", [])


def load_exclusions(exclusions_path: Path = EXCLUSIONS_PATH) -> Dict[str, Dict[str, Any]]:
    """Load explicit exclusion dictionary keyed by station slug."""
    if not exclusions_path.exists():
        return {}
    try:
        with open(exclusions_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            excl_list = data.get("exclusions", [])
            return {item["station_slug"]: item for item in excl_list if "station_slug" in item}
    except Exception as e:
        logger.warning(f"Could not load exclusions from {exclusions_path}: {e}")
        return {}


def log_quality_flag(
    station: str,
    column: str,
    reason: str,
    rows_affected: int = 0,
    timestamp_utc: Optional[str] = None
) -> None:
    """Append a FLAG action to data/cleaned/quality_log.csv."""
    QUALITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if timestamp_utc is None:
        timestamp_utc = datetime.now(timezone.utc).isoformat()

    import pandas as pd
    entry = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "station": station,
        "column": column,
        "action": "flag",
        "reason": reason,
        "rows_affected": int(rows_affected)
    }])
    header = not QUALITY_LOG_PATH.exists()
    entry.to_csv(QUALITY_LOG_PATH, mode="a", index=False, header=header)


def get_latest_fetched_timestamp(station_slug: str, sensor_id: int) -> Optional[str]:
    """
    Scan data/raw/ for existing files matching this station and sensor to find latest datetimeTo.
    Returns ISO 8601 UTC string or None if no prior data exists.
    """
    if not RAW_DIR.exists():
        return None

    pattern = f"openaq_{station_slug}_sensor_{sensor_id}_*.json"
    existing_files = list(RAW_DIR.glob(pattern))
    if not existing_files:
        return None

    latest_dt_utc = None
    for file_path in existing_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                results = content.get("results", [])
                for row in results:
                    dt_to = ((row.get("period") or {}).get("datetimeTo") or {}).get("utc")
                    if dt_to:
                        if latest_dt_utc is None or dt_to > latest_dt_utc:
                            latest_dt_utc = dt_to
        except Exception as e:
            logger.warning(f"Error reading existing raw file {file_path.name}: {e}")

    return latest_dt_utc


def fetch_sensor_hours(
    sensor_id: int,
    station_slug: str,
    parameter_name: str,
    datetime_from: Optional[str],
    api_key: str,
    limit: int = 1000
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Paginate all hourly records for a sensor from datetime_from onwards.
    Returns: (records, error_message).
    If an error occurs, returns (records_so_far, error_message).
    """
    url = f"https://api.openaq.org/v3/sensors/{sensor_id}/hours"
    headers = {"X-API-Key": api_key, "Accept": "application/json"}
    
    all_rows = []
    page = 1

    while True:
        params = {"limit": limit, "page": page}
        if datetime_from:
            params["datetime_from"] = datetime_from

        try:
            resp = safe_request(url, headers=headers, params=params)
        except Exception as e:
            err_msg = f"HTTP error during fetch on page {page}: {e}"
            logger.error(f"[{station_slug}] OpenAQ upstream failure for sensor {sensor_id} ({parameter_name}): {err_msg}")
            return all_rows, err_msg

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        all_rows.extend(results)
        logger.info(
            f"[{station_slug}] Sensor {sensor_id} ({parameter_name}) Page {page}: fetched {len(results)} rows (total {len(all_rows)})"
        )

        if len(results) < limit:
            break
        page += 1

    return all_rows, None


def save_raw_openaq_batch(
    station: Dict[str, Any],
    sensor_id: int,
    parameter_name: str,
    records: List[Dict[str, Any]],
    raw_dir: Path = RAW_DIR,
    datetime_from: Optional[str] = None
) -> Optional[Path]:
    """
    Save fetched raw JSON records to an immutable file in data/raw/.
    Uses atomic write to a temporary file first, then renames to target.
    """
    if not records:
        return None

    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"openaq_{station['slug']}_sensor_{sensor_id}_{parameter_name}_{fetched_at}.json"
    file_path = raw_dir / filename
    temp_path = raw_dir / f"{filename}.tmp_{os.getpid()}"

    payload = {
        "metadata": {
            "source": "OpenAQ v3",
            "station_slug": station["slug"],
            "station_name": station["name"],
            "location_id": station["location_id"],
            "sensor_id": sensor_id,
            "parameter": parameter_name,
            "provider": station.get("provider"),
            "owner": station.get("owner"),
            "licence": station.get("licence", "CC BY 4.0"),
            "fetched_at_utc": fetched_at,
            "source_url": f"https://api.openaq.org/v3/sensors/{sensor_id}/hours",
            "query": f"GET https://api.openaq.org/v3/sensors/{sensor_id}/hours?limit=1000&page=1..N"
                     + (f"&datetime_from={datetime_from}" if datetime_from else ""),
            "record_count": len(records)
        },
        "results": records
    }

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        # Atomic rename
        temp_path.replace(file_path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise e

    logger.info(f"Saved {len(records)} raw records to {file_path}")
    return file_path


def fetch_station(
    station: Dict[str, Any],
    api_key: str,
    fetch_aux: bool = True
) -> Dict[str, Any]:
    """
    Fetch PM2.5 (and optionally aux parameters) incrementally for one station.
    Returns a result dict:
    {
        "station_slug": slug,
        "status": "ok" | "up_to_date" | "failed",
        "saved_files": [Path, ...],
        "error": None | str,
        "details": {...}
    }
    """
    station_slug = station["slug"]
    station_name = station["name"]
    saved_files = []

    # Check exclusions first
    exclusions = load_exclusions()
    if station_slug in exclusions:
        excl_info = exclusions[station_slug]
        reason = excl_info.get("reason", "Excluded by config/exclusions.yaml")
        logger.warning(f"[{station_slug}] Station is in exclusion list: {reason}")
        log_quality_flag(
            station=station_slug,
            column="pm25",
            reason=f"station_excluded: {reason}",
            rows_affected=0
        )
        return {
            "station_slug": station_slug,
            "status": "failed",
            "saved_files": [],
            "error": reason,
            "is_excluded": True
        }

    # 1. PM2.5 sensor (required)
    pm25_sensor_id = station.get("pm25_sensor_id")
    if not pm25_sensor_id:
        err = f"No PM2.5 sensor ID configured for station {station_name}"
        logger.error(f"[{station_slug}] {err}")
        log_quality_flag(station=station_slug, column="pm25", reason="missing_sensor_id", rows_affected=0)
        return {
            "station_slug": station_slug,
            "status": "failed",
            "saved_files": [],
            "error": err
        }

    latest_ts = get_latest_fetched_timestamp(station_slug, pm25_sensor_id)
    if latest_ts:
        logger.info(f"[{station_slug}] Resuming PM2.5 from last fetched timestamp: {latest_ts}")
    else:
        logger.info(f"[{station_slug}] Starting full historical PM2.5 fetch from station inception")

    pm25_records, pm25_err = fetch_sensor_hours(
        sensor_id=pm25_sensor_id,
        station_slug=station_slug,
        parameter_name="pm25",
        datetime_from=latest_ts,
        api_key=api_key
    )

    if pm25_err and not pm25_records:
        # Complete failure to fetch required PM2.5 sensor
        log_quality_flag(
            station=station_slug,
            column="pm25",
            reason=f"upstream_fetch_failure: {pm25_err}",
            rows_affected=0
        )
        return {
            "station_slug": station_slug,
            "status": "failed",
            "saved_files": [],
            "error": pm25_err
        }

    # Filter out records that are <= latest_ts if any overlap returned by API
    if latest_ts and pm25_records:
        pm25_records = [
            r for r in pm25_records
            if ((r.get("period") or {}).get("datetimeTo") or {}).get("utc", "") > latest_ts
        ]

    if pm25_records:
        path = save_raw_openaq_batch(station, pm25_sensor_id, "pm25", pm25_records, datetime_from=latest_ts)
        if path:
            saved_files.append(path)
        pm25_status = "ok"
    else:
        if pm25_err:
            pm25_status = "failed"
        else:
            pm25_status = "up_to_date"
            logger.info(f"[{station_slug}] PM2.5 is up-to-date. No new hours to download.")

    # 2. Auxiliary sensors (PM1, RH, Temp, PM0.3 count for AirGradient)
    aux_errors = []
    if fetch_aux and station.get("aux_sensors"):
        for param, aux_id in station["aux_sensors"].items():
            aux_latest_ts = get_latest_fetched_timestamp(station_slug, aux_id)
            aux_records, a_err = fetch_sensor_hours(
                sensor_id=aux_id,
                station_slug=station_slug,
                parameter_name=param,
                datetime_from=aux_latest_ts,
                api_key=api_key
            )
            if a_err:
                aux_errors.append(f"{param}: {a_err}")
                log_quality_flag(station=station_slug, column=param, reason=f"upstream_aux_failure: {a_err}")
            if aux_latest_ts and aux_records:
                aux_records = [
                    r for r in aux_records
                    if ((r.get("period") or {}).get("datetimeTo") or {}).get("utc", "") > aux_latest_ts
                ]
            if aux_records:
                path = save_raw_openaq_batch(station, aux_id, param, aux_records, datetime_from=aux_latest_ts)
                if path:
                    saved_files.append(path)

    overall_status = pm25_status
    overall_err = pm25_err
    if aux_errors and overall_status == "up_to_date":
        overall_err = "; ".join(aux_errors)

    return {
        "station_slug": station_slug,
        "status": overall_status,
        "saved_files": saved_files,
        "error": overall_err
    }


def fetch_all_stations(fetch_aux: bool = True) -> Dict[str, Any]:
    """
    Fetch OpenAQ data for all stations configured in config/stations.yaml.
    Returns:
    {
        "saved_files": [Path, ...],
        "station_results": {slug: {...}},
        "failed_stations": [slug, ...],
        "all_succeeded": bool
    }
    """
    api_key = get_openaq_api_key()
    stations = load_stations_config()
    all_saved_files = []
    station_results = {}
    failed_stations = []

    logger.info(f"Starting OpenAQ data fetch for {len(stations)} stations...")
    for idx, station in enumerate(stations, 1):
        slug = station["slug"]
        logger.info(f"Fetching station {idx}/{len(stations)}: {station['name']} ({station['provider']})")
        res = fetch_station(station, api_key, fetch_aux=fetch_aux)
        station_results[slug] = res
        all_saved_files.extend(res.get("saved_files", []))
        if res["status"] == "failed":
            failed_stations.append(slug)

    logger.info(
        f"OpenAQ fetch complete. Status summary: {len(stations) - len(failed_stations)} ok/up-to-date, {len(failed_stations)} failed. Generated {len(all_saved_files)} new raw files."
    )

    return {
        "saved_files": all_saved_files,
        "station_results": station_results,
        "failed_stations": failed_stations,
        "all_succeeded": (len(failed_stations) == 0)
    }


def main():
    try:
        res = fetch_all_stations()
        if res["failed_stations"]:
            logger.warning(f"Fetch finished with failed stations: {res['failed_stations']}")
    except Exception as e:
        logger.error(f"Fetch failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
