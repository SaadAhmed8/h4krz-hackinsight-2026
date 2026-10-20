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


def atomic_write_csv(df: pd.DataFrame, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".csv.tmp")
    os.close(fd)
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def log_pipeline_run(
    status_str: str,
    error_trace: str = "",
    data_mode: str = "LIVE",
    predictions_produced: bool = False,
    n_daily_rows: int = 0
) -> None:
    run_log = Path("logs/prefect_runs.csv")
    run_log.parent.mkdir(parents=True, exist_ok=True)
    new_entry = pd.DataFrame(
        [
            {
                "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pipeline_status": status_str,
                "data_mode": data_mode,
                "predictions_produced": int(predictions_produced),
                "n_daily_rows": int(n_daily_rows),
                "error_trace": error_trace,
            }
        ]
    )
    if run_log.exists():
        try:
            existing = pd.read_csv(run_log)
            combined = pd.concat([existing, new_entry], ignore_index=True)
        except Exception:
            combined = new_entry
    else:
        combined = new_entry

    atomic_write_csv(combined, run_log)


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
        reasons = "; ".join(status.get("reasons", ["Severe unit or data error"]))
        raise PipelineExecutionError(f"Data Quality Agent returned status FAIL: {reasons}")

    if status["level"] == "WARN_STALE":
        logger.warning(
            f"DQ Agent warning: station/source staleness detected ({len(status.get('stale_entities', []))} entities). "
            f"Continuing pipeline execution with available valid rows."
        )
    else:
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
    csv_path = Path("data/processed/daily_station_table.csv")
    atomic_write_csv(daily_df, csv_path)
    logger.info(f"Built processed table: {len(daily_df)} valid station-days.")
    return daily_df


@task(name="4_run_model_predictions", retries=2, retry_delay_seconds=15)
def predict_task(daily_df: pd.DataFrame) -> bool:
    logger = get_run_logger()
    logger.info("Executing Model, Uncertainty & Group Fairness Module (Chapters 7 & 8)...")
    from src.model import run_model_pipeline
    try:
        success = run_model_pipeline()
        if success:
            logger.info("Model pipeline completed successfully: predictions and reports generated.")
            return True
        return False
    except Exception as exc:
        logger.error(f"Model prediction task encountered error: {exc}", exc_info=True)
        return False


@flow(name="lahore-pm25-hourly-pipeline", log_prints=True)
def hourly_aq_pipeline():
    data_mode = "LIVE"
    daily_df_len = 0
    try:
        cleaned_df, data_mode = fetch_and_clean_task()
        dq_df, status = dq_agent_task(cleaned_df)
        daily_df = build_processed_task(dq_df)
        daily_df_len = len(daily_df)
        preds_ok = predict_task(daily_df)
        # Honesty rule: Never log plain SUCCESS if predictions are not produced
        pipeline_status = "SUCCESS" if preds_ok else "PARTIAL_NO_MODEL"
        log_pipeline_run(
            pipeline_status,
            data_mode=data_mode,
            predictions_produced=preds_ok,
            n_daily_rows=daily_df_len
        )
    except Exception as exc:
        err_trace = traceback.format_exc()
        status_code = "FAILED_DQ" if isinstance(exc, (PipelineExecutionError, ContractError)) else "FAILED_SYS"
        log_pipeline_run(
            status_code,
            error_trace=err_trace,
            data_mode=data_mode,
            predictions_produced=False,
            n_daily_rows=daily_df_len
        )
        raise exc


def _ensure_prefect_server_url():
    """Point Prefect client to local server if port 4200 is reachable."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        res = s.connect_ex(("127.0.0.1", 4200))
        s.close()
        if res == 0:
            os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")
    except Exception:
        pass


if __name__ == "__main__":
    import time

    _ensure_prefect_server_url()

    if "--once" in sys.argv:
        hourly_aq_pipeline()
    else:
        # Check if immediate flow execution requested before entering scheduler
        if "--immediate" in sys.argv or "--run-now-and-loop" in sys.argv:
            print("[Hourly Scheduler] Running immediate pipeline execution on startup...")
            try:
                hourly_aq_pipeline()
            except Exception as e:
                print(f"[Hourly Scheduler] Initial execution warning: {e}")

        print("Hourly scheduler active. Waiting for minute :05 of each hour (PKT/UTC)...")
        last_triggered_slot = None

        while True:
            try:
                now = datetime.now(timezone.utc)
                current_slot = (now.year, now.month, now.day, now.hour)

                if now.minute == 5 and last_triggered_slot != current_slot:
                    last_triggered_slot = current_slot
                    print(f"[{datetime.now(timezone.utc).isoformat()}] Minute :05 detected. Triggering hourly_aq_pipeline()...")
                    try:
                        hourly_aq_pipeline()
                        print(f"[{datetime.now(timezone.utc).isoformat()}] Flow finished successfully.")
                    except Exception as flow_err:
                        print(f"[{datetime.now(timezone.utc).isoformat()}] Flow run caught error: {flow_err}")

                time.sleep(15)
            except KeyboardInterrupt:
                print("Hourly scheduler stopped by user.")
                break
            except Exception as loop_err:
                print(f"[Hourly Scheduler Loop Error]: {loop_err}")
                time.sleep(15)
