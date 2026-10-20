"""
Processed Data Warehouse Layer.
Generates:
  (a) data/processed/hourly_all.parquet:
      All stations joined with hourly Open-Meteo weather on UTC hour.
      Reports and logs missing weather hours to quality_log.csv without dropping.
  (b) data/processed/daily.parquet:
      Aggregated station-level dataset on PKT day boundaries (UTC+5, midnight to midnight).
      Features:
      - Deterministic collision-resistant record_id: sha256(station_slug + "_" + pkt_date)[:16]
      - 18-of-24 rule enforcement (requires >= 18 valid hours for valid daily mean)
      - Daily weather aggregates (mean/max temp, mean RH, mean/max wind, total precipitation)
      - Strictly historical lag features (today's mean, yesterday's mean, 7-day rolling mean without lookahead)
      - Calendar features (month, day of week)
      - Next-day target: target_next_day_pm25 = tomorrow's mean (strictly D+1 if valid)
"""
import sys
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
import yaml

from src.clean import log_quality_action

logger = logging.getLogger("process")

CLEANED_DIR = Path("data/cleaned")
PROCESSED_DIR = Path("data/processed")
CONFIG_PATH = Path("config/stations.yaml")

HOURLY_ALL_FILE = PROCESSED_DIR / "hourly_all.parquet"
DAILY_FILE = PROCESSED_DIR / "daily.parquet"


def generate_deterministic_record_id(station_slug: str, pkt_date_str: str) -> str:
    """Generate a collision-resistant 16-char deterministic hex ID for station-day pair."""
    key = f"{station_slug}_{pkt_date_str}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:16]


def build_hourly_all(cleaned_dir: Path = CLEANED_DIR, processed_dir: Path = PROCESSED_DIR) -> pd.DataFrame:
    """
    Join all cleaned station hourly series with cleaned weather series on UTC hour.
    Detects and logs any PM2.5 readings that have no matching weather to quality_log.csv.
    Saves to data/processed/hourly_all.parquet.
    """
    station_files = [
        sf for sf in sorted(cleaned_dir.glob("station_*.parquet"))
        if "ieee" not in sf.name.lower()
    ]
    weather_file = cleaned_dir / "weather_cleaned.parquet"

    if not station_files:
        raise FileNotFoundError("No cleaned station parquet files found in data/cleaned/")

    station_dfs = []
    for sf in station_files:
        try:
            df_st = pd.read_parquet(sf)
            station_dfs.append(df_st)
        except Exception as e:
            logger.error(f"Error reading {sf.name}: {e}")

    if not station_dfs:
        raise ValueError("Failed to load any cleaned station data.")

    df_stations = pd.concat(station_dfs, ignore_index=True)

    # Join with weather if available
    if weather_file.exists():
        df_weather = pd.read_parquet(weather_file)
        # Left join on timestamp_utc to preserve all station hours
        df_hourly = pd.merge(df_stations, df_weather, on="timestamp_utc", how="left")
        
        # Check missing weather hours
        missing_weather_mask = df_hourly["pm25"].notna() & df_hourly["weather_temp_c"].isna()
        n_missing_weather = int(missing_weather_mask.sum())
        if n_missing_weather > 0:
            logger.warning(
                f"Detected {n_missing_weather} non-null PM2.5 hours with missing weather data. Preserving hours as NaN."
            )
            for slug, sub_grp in df_hourly[missing_weather_mask].groupby("station_slug"):
                log_quality_action(
                    station=slug,
                    column="weather_data",
                    action="flag",
                    reason="missing_weather_match_for_pm25_hour",
                    rows_affected=len(sub_grp)
                )
    else:
        logger.warning("Cleaned weather file not found. Building hourly_all without weather.")
        df_hourly = df_stations

    # Enforce PKT timestamp and date helper columns (PKT = UTC + 5 hours)
    df_hourly["timestamp_pkt"] = df_hourly["timestamp_utc"] + pd.Timedelta(hours=5)
    df_hourly["pkt_date"] = df_hourly["timestamp_pkt"].dt.date.astype(str)

    processed_dir.mkdir(parents=True, exist_ok=True)
    out_hourly = processed_dir / "hourly_all.parquet"
    df_hourly.to_parquet(out_hourly, index=False)
    logger.info(f"Built {out_hourly} with {len(df_hourly)} rows across {df_hourly['station_slug'].nunique()} stations.")
    return df_hourly


def build_daily_mart(hourly_df: Optional[pd.DataFrame] = None, processed_dir: Path = PROCESSED_DIR) -> pd.DataFrame:
    """
    Aggregate hourly data into daily mart per station and PKT day.
    Enforces 18-of-24 rule, strictly historical lags, calendar features, and next-day target.
    """
    if hourly_df is None:
        if not HOURLY_ALL_FILE.exists():
            raise FileNotFoundError(f"{HOURLY_ALL_FILE} does not exist.")
        hourly_df = pd.read_parquet(HOURLY_ALL_FILE)

    records = []

    # Group by station
    for slug, group in hourly_df.groupby("station_slug"):
        group = group.sort_values("timestamp_utc").copy()
        
        if "pkt_date" not in group.columns:
            group["timestamp_pkt"] = group["timestamp_utc"] + pd.Timedelta(hours=5)
            group["pkt_date"] = group["timestamp_pkt"].dt.date.astype(str)

        st_name = group["station_name"].iloc[0] if "station_name" in group else slug
        loc_id = group["location_id"].iloc[0] if "location_id" in group else None
        provider = group["provider"].iloc[0] if "provider" in group else None
        owner = group["owner"].iloc[0] if "owner" in group else None
        licence = group["licence"].iloc[0] if "licence" in group and pd.notna(group["licence"].iloc[0]) else "UNKNOWN"

        daily_station = []
        for pkt_d, d_group in group.groupby("pkt_date"):
            n_total_hours = len(d_group)
            
            # Valid PM2.5 readings count
            valid_mask = d_group["pm25"].notna()
            if "is_flagged" in d_group.columns:
                valid_mask = valid_mask & (~d_group["is_flagged"])

            n_valid_pm25_hours = int(valid_mask.sum())

            # 18 of 24 rule
            is_valid_day = (n_valid_pm25_hours >= 18)
            daily_mean_pm25 = float(d_group.loc[valid_mask, "pm25"].mean()) if is_valid_day else np.nan
            validity_flag = "valid" if is_valid_day else "insufficient_hours"

            # Weather aggregates
            temp_mean = d_group["weather_temp_c"].mean() if "weather_temp_c" in d_group else np.nan
            temp_max = d_group["weather_temp_c"].max() if "weather_temp_c" in d_group else np.nan
            rh_mean = d_group["weather_rh_pct"].mean() if "weather_rh_pct" in d_group else np.nan
            wind_mean = d_group["weather_wind_speed_kmh"].mean() if "weather_wind_speed_kmh" in d_group else np.nan
            wind_max = d_group["weather_wind_speed_kmh"].max() if "weather_wind_speed_kmh" in d_group else np.nan
            precip_sum = d_group["weather_precip_mm"].sum() if "weather_precip_mm" in d_group else np.nan

            daily_station.append({
                "record_id": generate_deterministic_record_id(slug, str(pkt_d)),
                "station_slug": slug,
                "station_name": st_name,
                "location_id": loc_id,
                "provider": provider,
                "owner": owner,
                "licence": licence,
                "pkt_date": str(pkt_d),
                "n_total_hours": n_total_hours,
                "n_valid_pm25_hours": n_valid_pm25_hours,
                "is_valid_day": is_valid_day,
                "validity_flag": validity_flag,
                "pm25_daily_mean": daily_mean_pm25,
                "weather_temp_mean_c": temp_mean,
                "weather_temp_max_c": temp_max,
                "weather_rh_mean_pct": rh_mean,
                "weather_wind_mean_kmh": wind_mean,
                "weather_wind_max_kmh": wind_max,
                "weather_precip_sum_mm": precip_sum,
            })

        df_daily_st = pd.DataFrame(daily_station)
        if df_daily_st.empty:
            continue

        df_daily_st = df_daily_st.sort_values("pkt_date").reset_index(drop=True)
        dt_series = pd.to_datetime(df_daily_st["pkt_date"])

        # Calendar features
        df_daily_st["calendar_month"] = dt_series.dt.month
        df_daily_st["calendar_day_of_week"] = dt_series.dt.dayofweek
        df_daily_st["calendar_day_name"] = dt_series.dt.day_name()
        df_daily_st["is_weekend"] = df_daily_st["calendar_day_of_week"].isin([5, 6])

        # Lag features strictly past data only (no future leak)
        df_daily_st["pm25_lag_1d"] = df_daily_st["pm25_daily_mean"].shift(1)
        df_daily_st["pm25_lag_2d"] = df_daily_st["pm25_daily_mean"].shift(2)
        df_daily_st["pm25_lag_7d_rolling_mean"] = (
            df_daily_st["pm25_daily_mean"].shift(1).rolling(window=7, min_periods=1).mean()
        )

        # Baseline prediction: tomorrow's mean = today's mean
        df_daily_st["baseline_pred_next_day_pm25"] = df_daily_st["pm25_daily_mean"]

        # Next-day target: daily mean of day D+1 (only if D+1 exists and is valid)
        next_day_val = df_daily_st["pm25_daily_mean"].shift(-1)
        next_day_valid = df_daily_st["is_valid_day"].shift(-1).fillna(False)
        df_daily_st["target_next_day_pm25"] = np.where(next_day_valid, next_day_val, np.nan)

        records.append(df_daily_st)

    if not records:
        raise ValueError("No daily records generated.")

    all_daily_df = pd.concat(records, ignore_index=True)
    all_daily_df = all_daily_df.sort_values(["station_slug", "pkt_date"]).reset_index(drop=True)

    processed_dir.mkdir(parents=True, exist_ok=True)
    out_daily = processed_dir / "daily.parquet"
    all_daily_df.to_parquet(out_daily, index=False)
    logger.info(
        f"Built {out_daily} with {len(all_daily_df)} daily records ({all_daily_df['is_valid_day'].sum()} valid days)."
    )
    return all_daily_df


def process_all() -> Dict[str, Any]:
    """Execute complete processing pipeline: hourly_all.parquet + daily.parquet."""
    hourly_df = build_hourly_all()
    daily_df = build_daily_mart(hourly_df)
    return {"hourly_all": HOURLY_ALL_FILE, "daily": DAILY_FILE}


def main():
    try:
        process_all()
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
