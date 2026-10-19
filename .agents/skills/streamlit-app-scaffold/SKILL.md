---
name: streamlit-app-scaffold
description: "Guidelines and architecture for building lightweight, public, zero-login Hugging Face Space dashboards (Streamlit / Gradio) connected directly to live pipeline status JSON and daily tables."
---

# Streamlit App Scaffold Skill — HackInsight 2026

Architecture and patterns for building the public monitoring and prediction dashboard on Hugging Face Spaces.

## 1. Core Principles

- **Zero-login & Public Access:** Evaluators and team members must be able to view the app directly without authentication credentials.
- **Dynamic File Reading (No Hardcoded Mockups):**
  - Read pipeline health strictly from [logs/dq_status.json](file:///c:/Users/hasan/Downloads/Hack%20Insight/logs/dq_status.json).
  - Read station data and daily forecasts from `data/processed/daily_station_table.csv` (or `.parquet`).
  - Read execution history from `logs/prefect_runs.csv`.
- **Fault-Tolerant Loading:** Gracefully handle missing files during initial deployment or before the first pipeline run finishes.

## 2. Standard Layout Structure

A production-grade dashboard should feature three primary tabs/sections:

1. **Pipeline Health & DQ Monitor:**
   - Overall Status Badge (`OK`, `WARN`, `FAIL`).
   - Last evaluation timestamp in UTC and PKT.
   - Counters: Total rows, valid unimputed rows, imputed hours, flagged/stuck hours.
   - Stale data alerts (OpenAQ $> 3$h, OpenMeteo $> 168$h).
2. **Station Time-Series & Map:**
   - Station selector dropdown.
   - Historical PM2.5 readings vs tomorrow's prediction.
   - Data quality flag timeline (identifying filled gaps or stuck sensor masks).
3. **Model Performance & Audit Trail:**
   - Comparison vs naive baseline (`MAE_model` vs `MAE_naive`).
   - Prefect pipeline run log table (`logs/prefect_runs.csv`).

## 3. Reference Implementation Pattern (`app.py`)

```python
import json
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Lahore Air Quality Intelligence", layout="wide")

STATUS_FILE = Path("logs/dq_status.json")
PROCESSED_FILE = Path("data/processed/daily_station_table.csv")
RUNS_FILE = Path("logs/prefect_runs.csv")

st.title("Lahore Air Quality — Real-Time Pipeline & DQ Monitor")

# 1. Pipeline Status Header
if STATUS_FILE.exists():
    try:
        status_data = json.loads(STATUS_FILE.read_text())
        level = status_data.get("level", "UNKNOWN")
        color = "green" if level == "OK" else "orange" if level == "WARN" else "red"
        
        st.subheader(f"System Health: :{color}[{level}]")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Evaluated At (UTC)", status_data.get("evaluated_at_utc", "N/A"))
        col2.metric("Valid Unimputed Hours", status_data.get("valid_unimputed_rows", 0))
        col3.metric("Imputed Gap Hours", status_data.get("imputed_rows", 0))
        col4.metric("Flagged / Masked Hours", status_data.get("flagged_rows", 0))

        if status_data.get("stale_sources"):
            st.warning(f"Stale Sources Detected: {status_data['stale_sources']}")
    except Exception as e:
        st.error(f"Error parsing DQ status: {e}")
else:
    st.info("Pipeline waiting for initial execution. No `dq_status.json` detected.")

# 2. Daily Data & Forecasts
st.divider()
if PROCESSED_FILE.exists():
    df_daily = pd.read_csv(PROCESSED_FILE)
    st.subheader("Daily Station Aggregates (18/24h Rule Enforced)")
    st.dataframe(df_daily.tail(20), use_container_width=True)
else:
    st.warning("Daily processed station data is not yet generated.")

# 3. Pipeline Run History (Audit Deliverable)
st.divider()
if RUNS_FILE.exists():
    st.subheader("Prefect Hourly Pipeline Audit Trail")
    df_runs = pd.read_csv(RUNS_FILE)
    st.dataframe(df_runs.tail(10), use_container_width=True)
```

## 4. Hugging Face Spaces Deployment Checklist

1. Create a `requirements.txt` containing:
   ```text
   streamlit>=1.30.0
   pandas>=2.0.0
   pyarrow>=14.0.0
   plotly>=5.18.0
   ```
2. Store `README.md` with HF Space frontmatter:
   ```yaml
   ---
   title: Lahore AQ Intelligence
   emoji: 🌫️
   colorFrom: gray
   colorTo: red
   sdk: streamlit
   app_file: app.py
   pinned: false
   ---
   ```
3. Commit live data updates via automated scripts or sync tasks so the UI displays actual production results.
