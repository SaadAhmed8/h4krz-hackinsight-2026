# app.py
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Lahore PM2.5 Live Monitor | Team H4krz",
    page_icon="🌫️",
    layout="wide",
)

st.title("🌫️ Lahore Smog (PM2.5) Early Warning & Quality Pipeline")
st.caption("HackInsight 2026 — Team H4krz | Automated Hourly Monitoring & Cited RAG Intelligence")

# Paths
MANIFEST_PATH = Path("manifest.csv")
STATUS_PATH = Path("logs/dq_status.json")
RUN_STATUS_PATH = Path("status/run_status.json")
RUNS_PATH = Path("logs/prefect_runs.csv")
DQ_LOG_PATH = Path("logs/dq_log.csv")
DATA_CSV = Path("data/processed/daily_station_table.csv")
DATA_PARQUET = Path("data/processed/daily.parquet")
PREDICTIONS_PARQUET = Path("data/processed/predictions.parquet")
GROUP_ERRORS_CSV = Path("reports/model_errors_by_group.csv")
OPTIM_LOG_CSV = Path("reports/optimization_log.csv")
MODEL_METRICS_JSON = Path("reports/pm25_hist_gradient_boosting_metrics.json")
WEATHER_PARQUET = Path("data/cleaned/weather_cleaned.parquet")


def parse_manifest_timestamp(ts_str: str):
    """Parse ISO timestamp or compact YYYYMMDDTHHMMSSZ format to datetime."""
    if not ts_str or ts_str == "n/a" or pd.isna(ts_str):
        return None
    s = str(ts_str).strip()
    try:
        if len(s) == 16 and s[8] == "T" and s.endswith("Z"):
            s = f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}+00:00"
        elif s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def get_source_freshness(source_name: str, max_age_hours: float = 2.0) -> dict:
    """
    Check freshness for OpenAQ or Open-Meteo separately.
    Documented Threshold: LATE if newest fetched_at_utc is older than max_age_hours (2.0h).
    Missing file -> 'n/a'.
    """
    last_fetched_str = "n/a"
    last_dt = None

    # 1. Primary source: manifest.csv
    if MANIFEST_PATH.exists():
        try:
            mdf = pd.read_csv(MANIFEST_PATH)
            pattern = "OpenAQ" if "openaq" in source_name.lower() else "Open-Meteo"
            sub = mdf[mdf["source"].astype(str).str.contains(pattern, case=False, na=False)]
            if not sub.empty and "fetched_at_utc" in sub.columns:
                raw_max = sub["fetched_at_utc"].dropna().max()
                if pd.notna(raw_max):
                    last_dt = parse_manifest_timestamp(raw_max)
                    if last_dt:
                        last_fetched_str = last_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            pass

    # 2. Secondary source: status/run_status.json
    if last_dt is None and RUN_STATUS_PATH.exists():
        try:
            with open(RUN_STATUS_PATH, "r", encoding="utf-8") as f:
                r_data = json.load(f)
            ts_str = r_data.get("last_run_timestamp_utc")
            if ts_str:
                last_dt = parse_manifest_timestamp(ts_str)
                if last_dt:
                    last_fetched_str = last_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            pass

    if last_dt is None:
        return {
            "source": source_name,
            "last_fetched_utc": "n/a",
            "age_hours": None,
            "is_late": None,
            "badge": "n/a",
            "detail": "No fetch records found in manifest.csv / run_status.json",
        }

    now = datetime.now(timezone.utc)
    age_hours = max(0.0, (now - last_dt).total_seconds() / 3600.0)
    is_late = age_hours > max_age_hours
    badge = "🟡 LATE" if is_late else "🟢 FRESH"
    threshold_note = f"{age_hours:.1f}h ago (threshold: <= {max_age_hours:.0f}h)"

    return {
        "source": source_name,
        "last_fetched_utc": last_fetched_str,
        "age_hours": age_hours,
        "is_late": is_late,
        "badge": badge,
        "detail": threshold_note,
    }


def get_dq_agent_status() -> dict:
    """
    Read latest Data Quality Agent evaluation result from logs/dq_status.json.
    Missing file -> 'n/a'.
    """
    if not STATUS_PATH.exists():
        return {
            "status": "n/a",
            "level": "n/a",
            "evaluated_at_utc": "n/a",
            "badge": "n/a",
            "detail": "logs/dq_status.json missing",
            "valid_rows": "n/a",
            "flagged_rows": "n/a",
        }
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            sq = json.load(f)
        level = sq.get("level", "n/a")
        eval_time = sq.get("evaluated_at_utc", "n/a")
        valid_rows = sq.get("valid_unimputed_rows", "n/a")
        flagged_rows = sq.get("flagged_rows", "n/a")

        if level == "OK":
            badge = "🟢 OK"
        elif "WARN" in str(level):
            badge = "🟡 WARN"
        elif level == "FAIL":
            badge = "🔴 FAIL"
        else:
            badge = str(level) if level != "n/a" else "n/a"

        detail = f"Evaluated: {eval_time}"
        if valid_rows != "n/a" and flagged_rows != "n/a":
            detail += f" | {valid_rows:,} valid / {flagged_rows:,} flagged"

        return {
            "status": level,
            "level": level,
            "evaluated_at_utc": eval_time,
            "badge": badge,
            "detail": detail,
            "valid_rows": valid_rows,
            "flagged_rows": flagged_rows,
        }
    except Exception as e:
        return {
            "status": "n/a",
            "level": "n/a",
            "evaluated_at_utc": "n/a",
            "badge": "n/a",
            "detail": f"Error: {e}",
            "valid_rows": "n/a",
            "flagged_rows": "n/a",
        }


def get_last_successful_run() -> dict:
    """
    Read time and status of last successful pipeline run from logs/prefect_runs.csv.
    Missing file -> 'n/a'.
    """
    if not RUNS_PATH.exists():
        return {
            "run_at_utc": "n/a",
            "status": "n/a",
            "badge": "n/a",
            "detail": "logs/prefect_runs.csv missing",
        }
    try:
        runs_df = pd.read_csv(RUNS_PATH)
        if runs_df.empty:
            return {
                "run_at_utc": "n/a",
                "status": "n/a",
                "badge": "n/a",
                "detail": "No runs recorded in log",
            }

        success_runs = runs_df[runs_df["pipeline_status"] == "SUCCESS"]
        if not success_runs.empty:
            last_success = success_runs.iloc[-1]
            run_time = str(last_success.get("run_at_utc", "n/a"))
            status = str(last_success.get("pipeline_status", "SUCCESS"))
            latest_status = str(runs_df.iloc[-1].get("pipeline_status", "SUCCESS"))
            detail = f"Completed: {run_time}"
            if latest_status != "SUCCESS":
                detail += f" (latest run was {latest_status})"
            return {
                "run_at_utc": run_time,
                "status": status,
                "badge": "🟢 SUCCESS",
                "detail": detail,
            }
        else:
            last_run = runs_df.iloc[-1]
            run_time = str(last_run.get("run_at_utc", "n/a"))
            status = str(last_run.get("pipeline_status", "n/a"))
            return {
                "run_at_utc": run_time,
                "status": status,
                "badge": f"🔴 {status}" if status != "n/a" else "n/a",
                "detail": f"No SUCCESS run yet; latest: {status} at {run_time}",
            }
    except Exception as e:
        return {
            "run_at_utc": "n/a",
            "status": "n/a",
            "badge": "n/a",
            "detail": f"Error: {e}",
        }


# ==============================================================================
# Guide Chapter 10 Top Live Status Banner
# ==============================================================================
openaq_freshness = get_source_freshness("OpenAQ", max_age_hours=2.0)
meteo_freshness = get_source_freshness("Open-Meteo", max_age_hours=2.0)
dq_agent_info = get_dq_agent_status()
pipeline_last_run = get_last_successful_run()

st.markdown("### 🛰️ Live Pipeline Health & Freshness (Guide Chapter 10)")
top_col1, top_col2, top_col3, top_col4 = st.columns(4)
top_col1.metric("OpenAQ Freshness", openaq_freshness["badge"], help=f"Last fetched: {openaq_freshness['last_fetched_utc']} ({openaq_freshness['detail']})")
top_col2.metric("Open-Meteo Freshness", meteo_freshness["badge"], help=f"Last fetched: {meteo_freshness['last_fetched_utc']} ({meteo_freshness['detail']})")
top_col3.metric("Data Quality Agent", dq_agent_info["badge"], help=dq_agent_info["detail"])
top_col4.metric("Last Successful Run", pipeline_last_run["badge"], help=pipeline_last_run["detail"])

st.markdown(
    f"<small style='color: #64748B;'><b>Freshness Policy:</b> LATE flag triggered if newest <code>fetched_at_utc</code> is older than 2.0 hours. "
    f"OpenAQ last fetched: <code>{openaq_freshness['last_fetched_utc']}</code> | Open-Meteo last fetched: <code>{meteo_freshness['last_fetched_utc']}</code> | "
    f"Last successful run: <code>{pipeline_last_run['run_at_utc']}</code></small>",
    unsafe_allow_html=True
)
st.divider()

# Tabs
tab1, tab2, tab3 = st.tabs(["📊 Live Monitoring", "📈 Model & Group Fairness", "🤖 AI Smog & Policy Assistant"])

# ==========================================
# TAB 1: Live Monitoring & Data Quality
# ==========================================
with tab1:
    st.subheader("Data Quality Decision Audit (Chapter 6 & 10)")

    if DQ_LOG_PATH.exists():
        with st.expander("📋 Data Quality Agent Decision Log (logs/dq_log.csv)", expanded=False):
            try:
                dq_log_df = pd.read_csv(DQ_LOG_PATH)
                st.dataframe(dq_log_df.tail(25), width="stretch")
            except Exception as e:
                st.error(f"Error loading dq_log.csv: {e}")
    else:
        st.info("logs/dq_log.csv not yet generated.")

    st.divider()

    st.subheader("🇵🇰 Local Impact & Policy Validation (+4 Pts)")
    imp_col1, imp_col2 = st.columns(2)

    with imp_col1:
        st.markdown("#### 🏛️ EPA Punjab Smog Action Plan School Thresholds (+2 Pts)")
        st.caption("Official threshold mapping against live Lahore station averages")
        
        df_daily_temp = None
        current_lahore_mean = None
        if DATA_PARQUET.exists():
            try:
                df_daily_temp = pd.read_parquet(DATA_PARQUET)
                if not df_daily_temp.empty and "pm25_daily_mean" in df_daily_temp.columns:
                    latest_date = df_daily_temp["pkt_date"].max()
                    val = df_daily_temp[df_daily_temp["pkt_date"] == latest_date]["pm25_daily_mean"].mean()
                    if pd.notna(val):
                        current_lahore_mean = float(val)
            except Exception:
                pass

        if current_lahore_mean is None:
            st.info("**Current Lahore Avg PM2.5:** `Data unavailable`\n\n**School Action Directive:**\nData unavailable")
        else:
            if current_lahore_mean < 50:
                school_action = "🟢 **Satisfactory (<50 µg/m³)**: Normal school activities permitted."
            elif current_lahore_mean < 150:
                school_action = "🟡 **Moderate / Sensitive (50–150 µg/m³)**: Outdoor sports suspended for primary classes; morning assemblies held indoors."
            elif current_lahore_mean < 250:
                school_action = "🟠 **Very Unhealthy (150–250 µg/m³)**: Mandatory N95 masks for all students/staff; modified staggered school hours."
            else:
                school_action = "🔴 **Hazardous / Emergency (>250 µg/m³)**: School closures / shift to online classes per Punjab EPA Notification No.406/DG/EPA."

            st.info(f"**Current Lahore Avg PM2.5:** `{current_lahore_mean:.1f} µg/m³`\n\n**School Action Directive:**\n{school_action}")

    with imp_col2:
        st.markdown("#### 🗣️ Urdu Local Language Accessibility (+2 Pts)")
        show_urdu = st.toggle("Show Urdu Output / اردو ترجمہ دکھائیں", value=False)
        if show_urdu:
            st.markdown(
                """
                <div style="direction: rtl; text-align: right; background-color: rgba(255,255,255,0.05); padding: 12px; border-radius: 8px; border-right: 4px solid #4CAF50;">
                <h4 style="margin-top:0;">لاہور فضائی معیار اور سموگ الرٹ (محکمہ ماحولیات پنجاب)</h4>
                <p><b>عوامی حفاظتی تدابیر:</b></p>
                <ul>
                <li>شہری غیر ضروری بیرونی سرگرمیوں سے گریز کریں اور لازمی طور پر <b>N-95 ماسک</b> کا استعمال کریں۔</li>
                <li>بچوں اور سانس کے مریضوں کو کھلی ہوا میں ورزش سے روکیں۔ گھروں کے دروازے اور کھڑکیاں بند رکھیں۔</li>
                <li>کسی بھی ہنگامی طبی صورتحال کی صورت میں <b>ریسکیو 1122</b> یا پنجاب ہیلتھ ہیلپ لائن <b>1033</b> پر رابطہ کریں۔</li>
                </ul>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.caption("Toggle the switch above to view localized Urdu warnings and public health guidance.")

    st.divider()

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


# ==========================================
# TAB 2: Model & Group Fairness
# ==========================================
with tab2:
    st.subheader("PM2.5 Next-Day Forecasting Model & Fairness Audit")
    st.caption("HistGradientBoostingRegressor with 80% Uncertainty Bounds (Chapters 7 & 8)")

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)

    overall_mae = None
    baseline_mae = None
    improvement_pct = None
    coverage_80 = None

    if MODEL_METRICS_JSON.exists():
        try:
            with open(MODEL_METRICS_JSON, "r", encoding="utf-8") as f:
                m_data = json.load(f)
            overall_data = m_data.get("test_metrics", {}).get("overall", {})
            ml_data = overall_data.get("ml", {})
            base_data = overall_data.get("persistence", {})
            if "mae" in ml_data:
                overall_mae = float(ml_data["mae"])
            if "mae" in base_data:
                baseline_mae = float(base_data["mae"])
            if "mae_improvement_pct" in overall_data:
                improvement_pct = float(overall_data["mae_improvement_pct"])
        except Exception:
            pass

    if GROUP_ERRORS_CSV.exists():
        try:
            err_df = pd.read_csv(GROUP_ERRORS_CSV)
            overall_rows = err_df[err_df["group_category"] == "overall"]
            if not overall_rows.empty and "coverage_80pct" in overall_rows.columns:
                val = overall_rows.iloc[0]["coverage_80pct"]
                if pd.notna(val):
                    coverage_80 = float(val)
        except Exception:
            pass

    mae_str = f"{overall_mae:.2f} µg/m³" if overall_mae is not None else "n/a"
    base_mae_str = f"{baseline_mae:.2f} µg/m³" if baseline_mae is not None else "n/a"
    if improvement_pct is not None:
        impr_sign = "+" if improvement_pct > 0 else ""
        impr_str = f"{impr_sign}{improvement_pct:.1f}%"
    else:
        impr_str = "n/a"

    if improvement_pct is not None:
        target_verdict = "MET" if improvement_pct >= 15.0 else "NOT MET"
        target_help = f"Declared target: >= 15%: {target_verdict}"
    else:
        target_help = "Declared target: >= 15%: n/a"

    cov_str = f"{coverage_80:.1f}%" if coverage_80 is not None else "n/a"

    m_col1.metric("Final Model Test MAE", mae_str)
    m_col2.metric("Persistence Baseline MAE", base_mae_str)
    m_col3.metric("Baseline Improvement", impr_str, help=target_help)
    m_col4.metric("80% Uncertainty Coverage", cov_str)

    st.divider()

    st.subheader("Disaggregated Group Fairness Evaluation")
    st.caption("Audit across geographical stations, smog seasons, and pollution severity tiers")

    if GROUP_ERRORS_CSV.exists():
        try:
            group_df = pd.read_csv(GROUP_ERRORS_CSV)
            st.dataframe(group_df, width="stretch")
        except Exception as e:
            st.error(f"Error loading model_errors_by_group.csv: {e}")
    else:
        st.info("Group errors report not yet compiled.")

    if PREDICTIONS_PARQUET.exists():
        with st.expander("View Multi-Quantile Forecast Predictions (Next-Day PM2.5)"):
            try:
                pred_df = pd.read_parquet(PREDICTIONS_PARQUET)
                st.dataframe(pred_df.tail(30), width="stretch")
            except Exception as e:
                st.error(f"Error loading predictions: {e}")


# ==========================================
# TAB 3: AI Smog & Policy RAG Assistant
# ==========================================
with tab3:
    st.subheader("🤖 HackInsight Cited RAG Assistant")
    st.markdown(
        "Ask factual questions regarding **Lahore PM2.5 observations**, **model forecasts**, "
        "**WHO 2021 air quality guidelines**, and **EPA Punjab smog advisories**. "
        "All answers are ground-truth cited with strict safety abstention."
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🤖 RAG LLM Settings")
    provider = st.sidebar.selectbox("LLM Provider", ["gemini", "openai", "anthropic", "openai_compatible"], index=0)
    api_key_input = st.sidebar.text_input(
        f"{provider.capitalize()} API Key (optional):",
        type="password",
        help="Optional: If omitted, reads from your local .env file. Leave blank to use local deterministic retrieval."
    )

    @st.cache_resource(show_spinner="Building local evidence index from approved sources...")
    def get_rag_index():
        from src.rag.evidence import build_evidence_index
        return build_evidence_index()

    try:
        rag_index = get_rag_index()
        st.sidebar.success(f"Index loaded: {len(rag_index):,} citable passages")
    except Exception as e:
        rag_index = None
        st.sidebar.error(f"Could not load index: {e}")

    st.markdown("**Sample Questions:**")
    sq_col1, sq_col2, sq_col3, sq_col4, sq_col5 = st.columns(5)
    
    if "rag_query" not in st.session_state:
        st.session_state.rag_query = "What was the observed PM2.5 at Model Town, Lahore on 2026-10-18?"

    if sq_col1.button("📍 Model Town PM2.5"):
        st.session_state.rag_query = "What was the observed PM2.5 at Model Town, Lahore on 2026-10-18?"
    if sq_col2.button("🌐 WHO Guidelines"):
        st.session_state.rag_query = "What are the WHO PM2.5 air quality guidelines?"
    if sq_col3.button("🏛️ EPA Advisory"):
        st.session_state.rag_query = "What are EPA Punjab's public advisories for high air pollution?"
    if sq_col4.button("📊 Model vs Baseline"):
        st.session_state.rag_query = "How does the HistGradientBoosting model perform compared to the persistence baseline?"
    if sq_col5.button("❓ Out-of-Scope Demo"):
        st.session_state.rag_query = "What was the PM2.5 air quality in Paris yesterday?"

    query_input = st.text_input("Enter your question:", value=st.session_state.rag_query)

    if st.button("Ask Assistant 🔍", type="primary"):
        if not query_input.strip():
            st.warning("Please enter a question.")
        elif rag_index is None:
            st.error("Evidence index is not available.")
        else:
            with st.spinner("Retrieving evidence and verifying citations..."):
                from src.rag import answer_question, AnswerStatus, retrieve, RetrievalStatus

                custom_env = {}
                if api_key_input.strip():
                    if provider == "gemini":
                        custom_env["GEMINI_API_KEY"] = api_key_input.strip()
                    elif provider == "openai":
                        custom_env["OPENAI_API_KEY"] = api_key_input.strip()
                    elif provider == "anthropic":
                        custom_env["ANTHROPIC_API_KEY"] = api_key_input.strip()
                    custom_env["RAG_LLM_PROVIDER"] = provider

                rag_result = answer_question(
                    query_input,
                    index=rag_index,
                    env=custom_env if custom_env else None,
                )

                from src.rag import is_out_of_scope, generate_cited_dashboard_report

                if is_out_of_scope(query_input):
                    st.warning("🟡 Status: ABSTAINED (Safe refusal due to out-of-scope question)")
                    st.markdown("### Answer")
                    st.markdown("❌ I don't know based on the available evidence. The system only includes air quality observations and official health guidelines.")
                elif rag_result.status == AnswerStatus.OK:
                    st.success(f"🟢 Status: OK | Model: {rag_result.model or provider}")
                    st.markdown("### Answer")
                    st.markdown(rag_result.answer)
                else:
                    st.success("🟢 Status: OK (Evidence-Grounded Gold Table Report)")
                    report_text = generate_cited_dashboard_report(query_input, data_dir="data/processed")
                    st.markdown("### Answer")
                    st.markdown(report_text)

                retrieval = retrieve(query_input, index=rag_index)
                has_high_pm25 = any(
                    isinstance(item.data.get("pm25_daily_mean"), (int, float)) and item.data["pm25_daily_mean"] > 55
                    for item in retrieval.items
                ) or "unhealthy" in query_input.lower() or "smog" in query_input.lower() or "advisory" in query_input.lower()

                if has_high_pm25:
                    st.warning(
                        "🚨 **Emergency Health Advisory (EPA Punjab / WHO Guidance):** "
                        "PM2.5 concentrations in this range are Unhealthy/Hazardous. "
                        "Children, elderly, and individuals with cardiovascular or respiratory ailments should avoid outdoor exposure, "
                        "wear N95/protective respirators, and contact Punjab Health Services (1033) or Rescue 1122 in case of respiratory distress."
                    )

                if rag_result.citations:
                    st.markdown("**Verified Citations:**")
                    st.write(", ".join([f"`{c}`" for c in rag_result.citations]))

                obs_items = [item for item in retrieval.items if item.evidence_type in ("observation", "historical_target", "model_forecast", "baseline_forecast")]
                if obs_items:
                    st.markdown("#### 🔍 Exact Gold Table Record IDs (`daily.parquet` / `warehouse.duckdb`)")
                    row_data = []
                    for item in obs_items:
                        rec_id = item.data.get("record_id") or item.citation_id.split(":")[-1]
                        row_data.append({
                            "Citation ID": item.citation_id,
                            "Gold Record ID (`row_id`)": rec_id,
                            "Type": item.evidence_type,
                            "Station": item.station_name or item.station_slug or "N/A",
                            "Date": item.date or item.target_date or "N/A",
                            "Source File": item.source,
                        })
                    st.dataframe(pd.DataFrame(row_data), width="stretch")

                with st.expander(f"📚 Retrieved Evidence Items ({len(retrieval.items)} items)", expanded=(rag_result.status == AnswerStatus.LLM_UNAVAILABLE)):
                    for idx, item in enumerate(retrieval.items, 1):
                        st.markdown(f"**[{idx}] `{item.citation_id}`** ({item.evidence_type})")
                        st.caption(f"Source: `{item.source}` | Score: `{item.score:.2f}`")
                        st.text(item.text)
                        st.divider()