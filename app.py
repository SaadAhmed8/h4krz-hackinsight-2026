# app.py
import json
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Lahore PM2.5 Live Monitor | Team H4krz",
    page_icon="🌫️",
    layout="wide",
)

st.title("🌫️ Lahore Smog (PM2.5) Early Warning & Quality Pipeline")
st.caption("HackInsight 2026 — Team H4krz | Automated Hourly Monitoring")

# 1. Pipeline & Data Quality Health Status
STATUS_PATH = Path("logs/dq_status.json")
RUN_STATUS_PATH = Path("status/run_status.json")
RUNS_PATH = Path("logs/prefect_runs.csv")
DATA_CSV = Path("data/processed/daily_station_table.csv")
DATA_PARQUET = Path("data/processed/daily.parquet")

col1, col2, col3, col4 = st.columns(4)

if STATUS_PATH.exists():
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            status_data = json.load(f)
        
        level = status_data.get("level", "UNKNOWN")
        if level == "OK":
            col1.metric("Pipeline Health", "🟢 OK")
        elif level == "WARN":
            col1.metric("Pipeline Health", "🟡 WARN")
        else:
            col1.metric("Pipeline Health", "🔴 FAIL")

        col2.metric("Last Evaluated (UTC)", status_data.get("evaluated_at_utc", "N/A"))
        col3.metric("Valid Observations", f"{status_data.get('valid_unimputed_rows', 0):,}")
        col4.metric("Flagged / Anomalous", f"{status_data.get('flagged_rows', 0):,}")
    except Exception as e:
        st.error(f"Error loading status JSON: {e}")
elif RUN_STATUS_PATH.exists():
    try:
        with open(RUN_STATUS_PATH, "r", encoding="utf-8") as f:
            status_data = json.load(f)
        p_status = status_data.get("pipeline_status", "UNKNOWN")
        badge = "🟢 OK" if p_status == "completed_successfully" else "🟡 WARN"
        col1.metric("Pipeline Health", badge)
        col2.metric("Last Evaluated (UTC)", status_data.get("last_run_timestamp_utc", "N/A")[:19] + "Z")
        col3.metric("Sources Tracked", len(status_data.get("sources", {})))
        failed_cnt = len(status_data.get("failed_stations", []))
        col4.metric("Failed Stations", str(failed_cnt))
    except Exception as e:
        st.error(f"Error loading run_status.json: {e}")
else:
    col1.metric("Pipeline Health", "⏳ INITIALIZING")
    st.info("Waiting for first automated pipeline execution to generate status JSON...")

st.divider()

# 2. Daily Processed Station Data & Historical Predictions
st.subheader(r"Daily Station Data (Valid $\ge 18/24$ Non-Imputed Hours)")

df_daily = None
if DATA_PARQUET.exists():
    try:
        df_daily = pd.read_parquet(DATA_PARQUET)
    except Exception:
        df_daily = None
elif DATA_CSV.exists():
    try:
        df_daily = pd.read_csv(DATA_CSV)
    except Exception:
        df_daily = None

if df_daily is not None and not df_daily.empty:
    station_col = "station_slug" if "station_slug" in df_daily.columns else "station_id"
    date_col = "pkt_date" if "pkt_date" in df_daily.columns else "date_pkt"
    pm25_col = "pm25_daily_mean" if "pm25_daily_mean" in df_daily.columns else "pm25_mean"

    stations = sorted(df_daily[station_col].dropna().unique())
    selected_station = st.selectbox("Select Station:", stations)

    station_df = df_daily[df_daily[station_col] == selected_station].sort_values(date_col)

    cols_to_plot = [pm25_col]
    if "target_next_day_pm25" in station_df.columns:
        cols_to_plot.append("target_next_day_pm25")

    chart_data = station_df.set_index(date_col)[cols_to_plot]
    st.line_chart(chart_data)

    with st.expander("View Raw Processed Table (Contract Verification)"):
        st.dataframe(station_df, width="stretch")
else:
    st.info("Processed daily table not yet compiled.")

st.divider()

# 3. Prefect 24-Hour Run Audit Log
st.subheader("Prefect Automated Pipeline Run Audit")
if RUNS_PATH.exists():
    try:
        runs_df = pd.read_csv(RUNS_PATH)
        if not runs_df.empty:
            st.dataframe(runs_df.tail(24), width="stretch")
        else:
            st.text("No runs logged yet.")
    except Exception as e:
        st.error(f"Error reading prefect_runs.csv: {e}")
else:
    st.text("No prefect_runs.csv file found yet.")
