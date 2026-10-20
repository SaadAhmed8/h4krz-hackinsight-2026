# src/prefect_pipeline.py
import os
import sys
import traceback
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Dict
import pandas as pd
from prefect import flow, task, get_run_logger

from src.dq_schema import ContractError
from src.dq_agent import run_dq_agent, build_processed_daily_table


class PipelineExecutionError(RuntimeError):
    pass


def atomic_write_parquet(df: pd.DataFrame, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".parquet.tmp")
    os.close(fd)
    try:
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def log_pipeline_run(status_str: str, error_trace: str = "", data_mode: str = "LIVE") -> None:
    run_log = Path("logs/prefect_runs.csv")
    run_log.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame(
        [
            {
                "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pipeline_status": status_str,
                "data_mode": data_mode,
                "error_trace": error_trace,
            }
        ]
    )
    write_header = not run_log.exists()
    row.to_csv(run_log, mode="a", header=write_header, index=False)


def to_dq_contract(hourly: pd.DataFrame) -> pd.DataFrame:
    """Map data/processed/hourly_all.parquet columns onto the DQ agent contract."""
    ts = pd.to_datetime(hourly["timestamp_utc"], utc=True)
    return pd.DataFrame(
        {
            "station_id": hourly["station_slug"].astype(str),
            "ts_utc": ts,
            "pm25": hourly["pm25"],
            "source": "openaq",
            "rh": hourly.get("relativehumidity"),
            "temp_c": hourly.get("temperature"),
        }
    )


@task(name="1_fetch_and_clean_layer", retries=3, retry_delay_seconds=30)
def fetch_and_clean_task(hourly_path: str = "data/processed/hourly_all.parquet") -> Tuple[pd.DataFrame, str]:
    """Run the real warehouse pipeline (fetch -> verify -> clean -> process), then load the hourly table.
    No synthetic fallback: if real data is unavailable the run fails and is logged as failed.
    """
    logger = get_run_logger()
    from src.pipeline import run_pipeline
    run_pipeline()

    path = Path(hourly_path)
    if not path.exists():
        raise FileNotFoundError(f"Expected warehouse output not found at {path}.")

    df = to_dq_contract(pd.read_parquet(path))
    logger.info(f"Loaded {len(df)} rows from {path}")
    return df, "LIVE"


@task(name="2_run_dq_agent", retries=0)  # P4: Contract errors must not retry
def dq_agent_task(cleaned_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    logger = get_run_logger()
    dq_df, status = run_dq_agent(
        cleaned_df,
        log_path="logs/dq_log.csv",
        status_path="logs/dq_status.json",
    )
    
    # Finding P1: If status is FAIL, abort flow immediately!
    if status["level"] == "FAIL":
        reasons = "; ".join(status.get("reasons", ["Source/station staleness"]))
        raise PipelineExecutionError(f"Data Quality Agent returned status FAIL: {reasons}")

    logger.info(
        f"DQ Agent passed: status={status['level']}, "
        f"valid={status['valid_unimputed_rows']}, flagged={status['flagged_rows']}"
    )
    atomic_write_parquet(dq_df, Path("data/cleaned/stations_hourly_dq.parquet"))
    return dq_df, status


@task(name="3_build_processed_layer")
def build_processed_task(dq_df: pd.DataFrame) -> pd.DataFrame:
    logger = get_run_logger()
    weather_path = Path("data/cleaned/weather_daily.parquet")
    weather_df = pd.read_parquet(weather_path) if weather_path.exists() else None

    daily_df = build_processed_daily_table(dq_df, weather_daily_df=weather_df)
    
    # Finding P3: Fail if 0 valid daily rows
    if daily_df.empty:
        raise PipelineExecutionError("Processed daily table has 0 valid station-days. Prediction impossible.")

    out_path = Path("data/processed/daily_station_table.parquet")
    atomic_write_parquet(daily_df, out_path)
    daily_df.to_csv("data/processed/daily_station_table.csv", index=False)
    logger.info(f"Built processed table: {len(daily_df)} valid station-days.")
    return daily_df


@task(name="4_run_model_predictions", retries=2, retry_delay_seconds=15)
def predict_task(daily_df: pd.DataFrame) -> None:
    logger = get_run_logger()
    # UNFINISHED: model inference not yet integrated. Labelled per guide ch.12
    # ("Label anything simulated or unfinished"). Do NOT log predictions that did not run.
    logger.warning("UNFINISHED: model inference step not implemented; no predictions produced.")


@flow(name="lahore-pm25-hourly-pipeline", log_prints=True)
def hourly_aq_pipeline():
    data_mode = "LIVE"
    try:
        cleaned_df, data_mode = fetch_and_clean_task()
        dq_df, status = dq_agent_task(cleaned_df)
        daily_df = build_processed_task(dq_df)
        predict_task(daily_df)
        log_pipeline_run("SUCCESS", data_mode=data_mode)
    except Exception as exc:
        err_trace = traceback.format_exc()
        status_code = "FAILED_DQ" if isinstance(exc, (PipelineExecutionError, ContractError)) else "FAILED_SYS"
        log_pipeline_run(status_code, error_trace=err_trace, data_mode=data_mode)
        raise exc


if __name__ == "__main__":
    if "--once" in sys.argv:
        hourly_aq_pipeline()
    else:
        hourly_aq_pipeline.serve(
            name="lahore-pm25-hourly-deployment",
            cron="5 * * * *",
        )
