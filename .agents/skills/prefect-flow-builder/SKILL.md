---
name: prefect-flow-builder
description: "Rules and best practices for building robust, atomic, and retry-resilient Prefect hourly pipelines. Standardized for cron schedules, atomic file operations, and competition audit trail logging."
---

# Prefect Flow Builder Skill — HackInsight 2026

Operational conventions and pipeline guidelines for orchestrating the hourly Air Quality data pipeline using Prefect 3.x / 2.x. Reference implementation: [src/pipeline.py](file:///c:/Users/hasan/Downloads/Hack%20Insight/src/pipeline.py).

## 1. Schedule Specification

The pipeline executes at minute 5 of every hour to allow upstream station collectors (e.g. OpenAQ, Hawanama, OpenMeteo) 5 minutes to finish publishing past-hour readings.

- **Cron expression:** `5 * * * *`
- **Prefect deployment format:**
  ```python
  if __name__ == "__main__":
      hourly_aq_pipeline.serve(
          name="lahore-pm25-hourly-deployment",
          cron="5 * * * *",
      )
  ```

## 2. Mandatory Atomic Writes

Downstream processes (Streamlit UI, Hugging Face Space dashboards, ML inference jobs) read data concurrently. Direct file writes to `.parquet` or `.json` lead to race conditions where consumers read empty or partial files.

### Parquet Atomic Writer
```python
import os
import tempfile
from pathlib import Path
import pandas as pd

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
```

### JSON Atomic Writer (for Status Dashboards)
```python
import json

def atomic_write_json(data: dict, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
```

## 3. Retries & Fault Tolerance

Network tasks (calling external APIs or reading freshly synced remote directories) must be protected with retries:

```python
from prefect import task, flow, get_run_logger

@task(name="1_fetch_and_clean_layer", retries=3, retry_delay_seconds=60)
def fetch_and_clean_task(cleaned_data_path: str = "data/cleaned/stations_hourly.parquet") -> pd.DataFrame:
    ...

@task(name="4_run_model_predictions", retries=2, retry_delay_seconds=30)
def predict_task(daily_df: pd.DataFrame) -> None:
    ...
```

## 4. Run Execution Logging (`logs/prefect_runs.csv`)

For the competition audit deliverable, every pipeline execution must record its status (`SUCCESS` or `FAILED`) with timestamps and errors to an append-only CSV file.

```python
from datetime import datetime, timezone

def log_pipeline_run(status_str: str, error: str = "") -> None:
    run_log = Path("logs/prefect_runs.csv")
    run_log.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame(
        [
            {
                "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pipeline_status": status_str,
                "error": error,
            }
        ]
    )
    row.to_csv(run_log, mode="a", header=not run_log.exists(), index=False)

@flow(name="lahore-pm25-hourly-pipeline", log_prints=True)
def hourly_aq_pipeline():
    try:
        cleaned_df = fetch_and_clean_task()
        dq_df = dq_agent_task(cleaned_df)
        daily_df = build_processed_task(dq_df)
        predict_task(daily_df)
    except Exception as exc:
        log_pipeline_run("FAILED", str(exc)[:300])
        raise
    log_pipeline_run("SUCCESS")
```
