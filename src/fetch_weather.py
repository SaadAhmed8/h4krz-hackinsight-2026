"""
Open-Meteo Weather Data Acquisition with Forecast Fallback for Recent Days.
Fetches hourly weather variables:
- temperature_2m
- relative_humidity_2m
- wind_speed_10m
- precipitation

Sources:
1. Historical Archive API: archive-api.open-meteo.com/v1/archive (Copernicus ERA5 reanalysis)
2. Forecast API Fallback: api.open-meteo.com/v1/forecast (recent days up to today)
Timezone: GMT (UTC).
Location: Lahore (lat 31.52, lon 74.36).
"""
import os
import sys
import json
import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import yaml

from src.utils import safe_request

logger = logging.getLogger("fetch_weather")

RAW_DIR = Path("data/raw")
LAHORE_LAT = 31.52
LAHORE_LON = 74.36
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def get_earliest_station_date(config_path: Path = Path("config/stations.yaml")) -> str:
    """Find the earliest station start date from config/stations.yaml."""
    if not config_path.exists():
        return "2025-05-26"
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    dates = [s.get("since") for s in data.get("stations", []) if s.get("since")]
    return min(dates) if dates else "2025-05-26"


def get_latest_weather_date() -> Optional[str]:
    """Find latest date already fetched in data/raw/weather_*.json."""
    if not RAW_DIR.exists():
        return None
    weather_files = list(RAW_DIR.glob("weather_lahore_*.json"))
    if not weather_files:
        return None

    latest_date_str = None
    for wf in weather_files:
        try:
            with open(wf, "r", encoding="utf-8") as f:
                data = json.load(f)
                meta = data.get("metadata", {})
                end_d = meta.get("end_date")
                if end_d:
                    if latest_date_str is None or end_d > latest_date_str:
                        latest_date_str = end_d
        except Exception as e:
            logger.warning(f"Error reading weather file {wf.name}: {e}")

    return latest_date_str


def fetch_weather_archive(start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
    """Fetch hourly weather from Open-Meteo ERA5 archive endpoint."""
    params = {
        "latitude": LAHORE_LAT,
        "longitude": LAHORE_LON,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "timezone": "GMT"
    }
    resp = safe_request(OPEN_METEO_ARCHIVE_URL, params=params)
    return {
        "source": "Open-Meteo Historical Weather API (ERA5)",
        "endpoint": OPEN_METEO_ARCHIVE_URL,
        "weather_source": "archive",
        "url": resp.url,
        "data": resp.json()
    }


def fetch_weather_forecast(past_days: int = 3, forecast_days: int = 1) -> Optional[Dict[str, Any]]:
    """Fetch recent hourly weather from Open-Meteo forecast endpoint as fallback."""
    params = {
        "latitude": LAHORE_LAT,
        "longitude": LAHORE_LON,
        "past_days": past_days,
        "forecast_days": forecast_days,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "timezone": "GMT"
    }
    resp = safe_request(OPEN_METEO_FORECAST_URL, params=params)
    return {
        "source": "Open-Meteo Forecast Weather API",
        "endpoint": OPEN_METEO_FORECAST_URL,
        "weather_source": "forecast",
        "url": resp.url,
        "data": resp.json()
    }


def save_raw_weather(
    weather_payload: Dict[str, Any],
    start_date: str,
    end_date: str,
    weather_source: str,
    raw_dir: Path = RAW_DIR
) -> Path:
    """Save raw weather JSON with atomic rename."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"weather_lahore_{weather_source}_{start_date}_{end_date}_{fetched_at}.json"
    file_path = raw_dir / filename
    temp_path = raw_dir / f"{filename}.tmp_{os.getpid()}"

    data = weather_payload["data"]
    hourly = data.get("hourly", {})
    timestamps = hourly.get("time", [])

    payload = {
        "metadata": {
            "source": weather_payload["source"],
            "attribution": "Weather data by Open-Meteo.com",
            "source_url": weather_payload["url"],
            "endpoint": weather_payload["endpoint"],
            "weather_source": weather_source,
            "latitude": LAHORE_LAT,
            "longitude": LAHORE_LON,
            "start_date": start_date,
            "end_date": end_date,
            "fetched_at_utc": fetched_at,
            "row_count": len(timestamps),
            "licence": "CC BY 4.0"
        },
        "data": data
    }

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        temp_path.replace(file_path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise e

    logger.info(f"Saved {len(timestamps)} hourly weather ({weather_source}) records to {file_path}")
    return file_path


def fetch_weather(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    raw_dir: Path = RAW_DIR
) -> List[Path]:
    """
    Fetch historical weather from archive, and recent days from forecast endpoint fallback.
    Returns list of saved raw file paths.
    """
    saved_files = []
    earliest_date = get_earliest_station_date()
    today_str = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")

    latest_stored_date = get_latest_weather_date()

    if start_date is None:
        if latest_stored_date:
            next_start = datetime.strptime(latest_stored_date, "%Y-%m-%d").date() + timedelta(days=1)
            start_date = next_start.strftime("%Y-%m-%d")
            logger.info(f"Resuming weather from previous date: {start_date}")
        else:
            start_date = earliest_date
            logger.info(f"Starting initial weather fetch from earliest station date: {start_date}")

    if end_date is None:
        end_date = today_str

    if start_date <= end_date:
        # 1. Fetch archive portion (up to today)
        try:
            logger.info(f"Querying Open-Meteo Archive API from {start_date} to {end_date} (GMT)...")
            res_arch = fetch_weather_archive(start_date=start_date, end_date=end_date)
            if res_arch:
                p = save_raw_weather(res_arch, start_date, end_date, "archive", raw_dir=raw_dir)
                saved_files.append(p)
        except Exception as e:
            logger.warning(f"Archive fetch failed for {start_date} to {end_date}: {e}. Trying forecast fallback...")

    # 2. Always fetch forecast fallback for the most recent 2 days to ensure tail coverage
    try:
        logger.info("Querying Open-Meteo Forecast API for recent days (past_days=2, forecast_days=1)...")
        res_fore = fetch_weather_forecast(past_days=2, forecast_days=1)
        if res_fore:
            f_times = res_fore["data"].get("hourly", {}).get("time", [])
            if f_times:
                f_start = f_times[0].split("T")[0]
                f_end = f_times[-1].split("T")[0]
                p_fore = save_raw_weather(res_fore, f_start, f_end, "forecast", raw_dir=raw_dir)
                saved_files.append(p_fore)
    except Exception as e:
        logger.error(f"Forecast API fallback fetch failed: {e}")

    return saved_files


def main():
    try:
        fetch_weather()
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
