"""
Data Cleaning and Validation Layer.
- Reads raw OpenAQ JSON files and Open-Meteo weather JSON.
- Deduplicates timestamps, enforces strong dtypes and UTC timezone-aware index.
- Reindexes to full regular hourly grid (missing hours explicit NaN, not dropped).
- Validates values and flags anomalies:
  * negative PM2.5 -> flagged
  * extreme values (> 1000 ug/m3) -> flagged
  * stuck runs (>= 6 identical consecutive non-zero readings) -> flagged
- Logs every decision to data/cleaned/quality_log.csv:
  timestamp_utc, station, column, action, reason, rows_affected
- Saves standardized Parquet files to data/cleaned/.
"""
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np
import yaml

logger = logging.getLogger("clean")

RAW_DIR = Path("data/raw")
CLEANED_DIR = Path("data/cleaned")
CONFIG_PATH = Path("config/stations.yaml")
QUALITY_LOG_PATH = CLEANED_DIR / "quality_log.csv"

# Quality validation rule thresholds (easily inspectable for viva defense)
QUALITY_RULES = {
    "pm25_min_valid": 0.0,
    "pm25_max_sanity": 1000.0,
    "stuck_sensor_min_run_hours": 6,
    "rh_min_valid": 0.0,
    "rh_max_valid": 100.0,
    "temp_min_valid": -20.0,
    "temp_max_valid": 60.0
}


def log_quality_action(
    station: str,
    column: str,
    action: str,  # 'fix' | 'fill' | 'flag' | 'drop'
    reason: str,
    rows_affected: int,
    timestamp_utc: Optional[str] = None,
    log_path: Path = QUALITY_LOG_PATH
) -> None:
    """Append a decision entry to data/cleaned/quality_log.csv."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if timestamp_utc is None:
        timestamp_utc = datetime.now(timezone.utc).isoformat()

    entry = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "station": station,
        "column": column,
        "action": action,
        "reason": reason,
        "rows_affected": int(rows_affected)
    }])

    # Header only if file doesn't exist
    header = not log_path.exists()
    entry.to_csv(log_path, mode="a", index=False, header=header)


def load_raw_station_records(station_slug: str, raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """
    Load all raw JSON files for a given station across sensors and merge into a tidy hourly DataFrame.
    """
    matching_files = list(raw_dir.glob(f"openaq_{station_slug}_sensor_*.json"))
    if not matching_files:
        logger.warning(f"No raw files found for station slug: {station_slug}")
        return pd.DataFrame()

    dfs_by_param = {}
    
    for mf in matching_files:
        try:
            with open(mf, "r", encoding="utf-8") as f:
                data = json.load(f)
                meta = data.get("metadata", {})
                param = meta.get("parameter", "pm25")
                results = data.get("results", [])
                
                rows = []
                for item in results:
                    period = item.get("period", {})
                    dt_to_utc = (period.get("datetimeTo") or {}).get("utc")
                    val = item.get("value")
                    if dt_to_utc is not None and val is not None:
                        rows.append({"timestamp_utc": dt_to_utc, param: float(val)})
                
                if rows:
                    df_param = pd.DataFrame(rows)
                    if param in dfs_by_param:
                        dfs_by_param[param] = pd.concat([dfs_by_param[param], df_param], ignore_index=True)
                    else:
                        dfs_by_param[param] = df_param
        except Exception as e:
            logger.error(f"Error reading {mf.name}: {e}")

    if not dfs_by_param:
        return pd.DataFrame()

    # Merge across parameters by timestamp_utc
    merged_df = None
    for param, df in dfs_by_param.items():
        init_len = len(df)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc")
        deduped_len = len(df)
        if init_len > deduped_len:
            log_quality_action(
                station=station_slug,
                column=param,
                action="drop",
                reason="duplicate_timestamp",
                rows_affected=init_len - deduped_len
            )

        if merged_df is None:
            merged_df = df
        else:
            merged_df = pd.merge(merged_df, df, on="timestamp_utc", how="outer")

    if merged_df is not None:
        merged_df = merged_df.sort_values("timestamp_utc").reset_index(drop=True)
    return merged_df


def clean_station_series(
    station: Dict[str, Any],
    raw_dir: Path = RAW_DIR,
    cleaned_dir: Path = CLEANED_DIR
) -> Optional[Path]:
    """
    Process, validate, reindex and clean raw series for a single station.
    Saves data/cleaned/station_{slug}.parquet.
    """
    slug = station["slug"]
    if slug == "ieee_punjab_univ" or station.get("owner") == "unverified":
        logger.info(f"Excluding unverified station {slug} per licensing rules.")
        st_clean = cleaned_dir / f"station_{slug}.parquet"
        if st_clean.exists():
            st_clean.unlink()
        return None

    station_name = station["name"]
    df = load_raw_station_records(slug, raw_dir=raw_dir)
    
    if df.empty or "pm25" not in df.columns:
        logger.warning(f"No PM2.5 records found to clean for station {slug}")
        return None

    # Enforce UTC datetime index
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc").set_index("timestamp_utc")

    # Reindex to full regular hourly grid from first to last observation
    min_time = df.index.min().floor("h")
    max_time = df.index.max().ceil("h")
    full_hourly_idx = pd.date_range(start=min_time, end=max_time, freq="1h", tz="UTC", name="timestamp_utc")
    
    missing_hours = len(full_hourly_idx) - len(df)
    if missing_hours > 0:
        log_quality_action(
            station=slug,
            column="timestamp_utc",
            action="fill",
            reason="missing_hourly_timestamp_grid_gap",
            rows_affected=missing_hours
        )

    # Reindex preserving missing hours as explicit NaN
    df_clean = df.reindex(full_hourly_idx)

    # Add metadata columns
    df_clean["station_slug"] = slug
    df_clean["station_name"] = station_name
    df_clean["location_id"] = station["location_id"]
    df_clean["provider"] = station["provider"]
    df_clean["owner"] = station["owner"]
    df_clean["licence"] = station.get("licence", "UNKNOWN")

    # Initialize quality flags
    df_clean["is_flagged"] = False
    df_clean["flag_reason"] = ""

    # Rule 1: Negative PM2.5 values
    neg_mask = df_clean["pm25"] < QUALITY_RULES["pm25_min_valid"]
    n_neg = neg_mask.sum()
    if n_neg > 0:
        df_clean.loc[neg_mask, "is_flagged"] = True
        df_clean.loc[neg_mask, "flag_reason"] = df_clean.loc[neg_mask, "flag_reason"].apply(
            lambda r: (r + ";negative_value").strip(";")
        )
        log_quality_action(
            station=slug,
            column="pm25",
            action="flag",
            reason="negative_value",
            rows_affected=n_neg
        )

    # Rule 2: Physical Sanity Maximum (> 1000 ug/m3)
    max_mask = df_clean["pm25"] > QUALITY_RULES["pm25_max_sanity"]
    n_max = max_mask.sum()
    if n_max > 0:
        df_clean.loc[max_mask, "is_flagged"] = True
        df_clean.loc[max_mask, "flag_reason"] = df_clean.loc[max_mask, "flag_reason"].apply(
            lambda r: (r + ";extreme_value").strip(";")
        )
        log_quality_action(
            station=slug,
            column="pm25",
            action="flag",
            reason="extreme_value_exceeds_1000",
            rows_affected=n_max
        )

    # Rule 3: Stuck sensor runs (>= 6 consecutive identical non-zero values)
    pm25_s = df_clean["pm25"]
    is_same = (pm25_s == pm25_s.shift(1)) & pm25_s.notna() & (pm25_s > 0)
    run_id = (~is_same).cumsum()
    run_counts = df_clean.groupby(run_id)["pm25"].transform("count")
    stuck_mask = is_same & (run_counts >= QUALITY_RULES["stuck_sensor_min_run_hours"])
    n_stuck = stuck_mask.sum()
    if n_stuck > 0:
        df_clean.loc[stuck_mask, "is_flagged"] = True
        df_clean.loc[stuck_mask, "flag_reason"] = df_clean.loc[stuck_mask, "flag_reason"].apply(
            lambda r: (r + ";stuck_sensor").strip(";")
        )
        log_quality_action(
            station=slug,
            column="pm25",
            action="flag",
            reason=f"stuck_sensor_identical_{QUALITY_RULES['stuck_sensor_min_run_hours']}hrs",
            rows_affected=n_stuck
        )

    # Valid reading mask (for downstream consumption: not null and not flagged)
    df_clean["is_valid_reading"] = df_clean["pm25"].notna() & (~df_clean["is_flagged"])

    cleaned_dir.mkdir(parents=True, exist_ok=True)
    output_file = cleaned_dir / f"station_{slug}.parquet"
    df_clean.reset_index().to_parquet(output_file, index=False)
    logger.info(f"Saved cleaned parquet for {slug} ({len(df_clean)} rows) to {output_file}")
    return output_file


def clean_weather_series(raw_dir: Path = RAW_DIR, cleaned_dir: Path = CLEANED_DIR) -> Optional[Path]:
    """
    Clean and standardize Open-Meteo hourly weather (archive + forecast fallback)
    into data/cleaned/weather_cleaned.parquet.
    """
    weather_files = sorted(raw_dir.glob("weather_lahore_*.json"))
    if not weather_files:
        logger.warning("No raw weather files found to clean.")
        return None

    all_dfs = []
    for wf in weather_files:
        try:
            with open(wf, "r", encoding="utf-8") as f:
                content = json.load(f)
                meta = content.get("metadata", {})
                w_src = meta.get("weather_source", "archive")
                hourly = content.get("data", {}).get("hourly", {})
                if hourly and "time" in hourly:
                    df_w = pd.DataFrame(hourly)
                    df_w["weather_source"] = w_src
                    all_dfs.append(df_w)
        except Exception as e:
            logger.error(f"Error reading weather file {wf.name}: {e}")

    if not all_dfs:
        return None

    merged = pd.concat(all_dfs, ignore_index=True)
    merged["timestamp_utc"] = pd.to_datetime(merged["time"], utc=True)
    merged = merged.drop(columns=["time"])

    # If duplicate timestamps exist between archive and forecast, prioritize archive
    merged = merged.sort_values(by=["timestamp_utc", "weather_source"])
    merged = merged.drop_duplicates(subset=["timestamp_utc"], keep="first").sort_values("timestamp_utc")

    # Rename columns
    rename_cols = {
        "temperature_2m": "weather_temp_c",
        "relative_humidity_2m": "weather_rh_pct",
        "wind_speed_10m": "weather_wind_speed_kmh",
        "precipitation": "weather_precip_mm"
    }
    merged = merged.rename(columns=rename_cols)

    # Full regular hourly grid reindex
    min_time = merged["timestamp_utc"].min().floor("h")
    max_time = merged["timestamp_utc"].max().ceil("h")
    grid = pd.date_range(start=min_time, end=max_time, freq="1h", tz="UTC", name="timestamp_utc")
    
    merged = merged.set_index("timestamp_utc").reindex(grid).reset_index()

    cleaned_dir.mkdir(parents=True, exist_ok=True)
    out_path = cleaned_dir / "weather_cleaned.parquet"
    merged.to_parquet(out_path, index=False)
    logger.info(f"Saved cleaned weather ({len(merged)} rows) to {out_path}")
    
    # Also build weather_daily.parquet
    build_weather_daily(cleaned_dir)
    return out_path


def build_weather_daily(cleaned_dir: Path = CLEANED_DIR) -> Path:
    """
    Build data/cleaned/weather_daily.parquet from weather_cleaned.parquet.
    Groups hourly ERA5 weather by PKT day (timestamp_utc + 5h), computes daily aggregates.
    """
    cleaned_weather_path = cleaned_dir / "weather_cleaned.parquet"
    if not cleaned_weather_path.exists():
        logger.warning(f"{cleaned_weather_path} not found. Cannot build weather_daily.parquet.")
        return cleaned_dir / "weather_daily.parquet"

    df_w = pd.read_parquet(cleaned_weather_path)
    if df_w.empty:
        return cleaned_dir / "weather_daily.parquet"

    df_w["timestamp_utc"] = pd.to_datetime(df_w["timestamp_utc"], utc=True)
    df_w["timestamp_pkt"] = df_w["timestamp_utc"] + pd.Timedelta(hours=5)
    df_w["date_pkt"] = df_w["timestamp_pkt"].dt.date.astype(str)

    records = []
    for date_pkt, grp in df_w.groupby("date_pkt"):
        records.append({
            "date_pkt": str(date_pkt),
            "start_time_utc": grp["timestamp_utc"].min().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time_utc": grp["timestamp_utc"].max().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "weather_temp_mean_c": float(grp["weather_temp_c"].mean()) if "weather_temp_c" in grp else np.nan,
            "weather_temp_max_c": float(grp["weather_temp_c"].max()) if "weather_temp_c" in grp else np.nan,
            "weather_temp_min_c": float(grp["weather_temp_c"].min()) if "weather_temp_c" in grp else np.nan,
            "weather_rh_mean_pct": float(grp["weather_rh_pct"].mean()) if "weather_rh_pct" in grp else np.nan,
            "weather_wind_mean_kmh": float(grp["weather_wind_speed_kmh"].mean()) if "weather_wind_speed_kmh" in grp else np.nan,
            "weather_wind_max_kmh": float(grp["weather_wind_speed_kmh"].max()) if "weather_wind_speed_kmh" in grp else np.nan,
            "weather_precip_sum_mm": float(grp["weather_precip_mm"].sum()) if "weather_precip_mm" in grp else np.nan,
        })

    df_daily_w = pd.DataFrame(records)
    out_path = cleaned_dir / "weather_daily.parquet"
    df_daily_w.to_parquet(out_path, index=False)
    logger.info(f"Built {out_path} ({len(df_daily_w)} daily rows from {len(df_w)} hourly rows).")
    return out_path


def clean_all() -> Dict[str, Any]:
    """Clean all stations and weather files."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config {CONFIG_PATH} not found.")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        stations = yaml.safe_load(f).get("stations", [])

    station_files = []
    for s in stations:
        if s.get("slug") == "ieee_punjab_univ" or s.get("owner") == "unverified":
            logger.info(f"Skipping unverified station {s.get('slug')} per licensing rules.")
            st_clean = CLEANED_DIR / f"station_{s.get('slug')}.parquet"
            if st_clean.exists():
                st_clean.unlink()
            continue
        p = clean_station_series(s)
        if p:
            station_files.append(p)

    weather_file = clean_weather_series()
    weather_daily_file = build_weather_daily()
    return {"stations": station_files, "weather": weather_file, "weather_daily": weather_daily_file}


def main():
    try:
        clean_all()
    except Exception as e:
        logger.error(f"Cleaning failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
