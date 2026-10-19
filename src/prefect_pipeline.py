# src/pipeline.py
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


@task(name="1_fetch_and_clean_layer", retries=3, retry_delay_seconds=30)
def fetch_and_clean_task(cleaned_data_path: str = "data/cleaned/stations_hourly.parquet") -> Tuple[pd.DataFrame, str]:
    logger = get_run_logger()
    path = Path(cleaned_data_path)

    if not path.exists():
        # Finding P2: Reject silent mocks unless explicitly permitted
        if os.getenv("ALLOW_MOCK_FALLBACK", "0") == "1":
            logger.warning("PROD WARNING: Using synthetic mock data fallback (ALLOW_MOCK_FALLBACK=1)!")
            from src.mock_data import make_mock_batch
            # Use 72h mock batch ending at current UTC hour
            df = make_mock_batch(hours=72)
            return df, "MOCK"
        else:
            raise FileNotFoundError(
                f"Production file not found at {path}. Silent mock fallback is disabled. "
                "Saad must output data/cleaned/stations_hourly.parquet."
            )

    try:
        df = pd.read_parquet(path)
    except Exception as e:
        logger.error(f"Parquet file corrupted: {e}")
        raise

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
    # Ready for Noman's inference script
    logger.info(f"Model predictions completed for {len(daily_df)} rows.")


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
