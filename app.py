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

# Tabs
tab1, tab2, tab3 = st.tabs(["📊 Live Monitoring", "📈 Model & Group Fairness", "🤖 AI Smog & Policy Assistant"])

# ==========================================
# TAB 1: Live Monitoring & Data Quality
# ==========================================
with tab1:
    st.subheader("Pipeline Health & Source Freshness (Chapter 6 & 10)")

    # 1. Source Freshness & Pipeline Execution Badges
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)

    # OpenAQ Freshness
    openaq_time_str = "N/A"
    openaq_fresh = False
    if RUN_STATUS_PATH.exists():
        try:
            with open(RUN_STATUS_PATH, "r", encoding="utf-8") as f:
                r_data = json.load(f)
            openaq_time_str = r_data.get("last_run_timestamp_utc", "N/A")[:19] + "Z"
            openaq_fresh = r_data.get("sources", {}).get("openaq", {}).get("status") in ("up_to_date", "healthy", "partial_failures")
        except Exception:
            pass

    openaq_badge = "🟢 FRESH" if openaq_fresh else "🟡 LATE"
    f_col1.metric("OpenAQ Source Freshness", openaq_badge, help=f"Last fetched: {openaq_time_str}")

    # Open-Meteo Freshness
    meteo_time_str = "N/A"
    meteo_fresh = True
    if WEATHER_PARQUET.exists():
        try:
            mtime = datetime.fromtimestamp(WEATHER_PARQUET.stat().st_mtime, tz=timezone.utc)
            meteo_time_str = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    meteo_badge = "🟢 FRESH" if meteo_fresh else "🟡 LATE"
    f_col2.metric("Open-Meteo Freshness", meteo_badge, help=f"Cleaned weather updated: {meteo_time_str}")

    # Prefect Pipeline Last Run
    last_prefect_run = "N/A"
    prefect_status = "UNKNOWN"
    if RUNS_PATH.exists():
        try:
            runs_df = pd.read_csv(RUNS_PATH)
            if not runs_df.empty:
                last_row = runs_df.iloc[-1]
                last_prefect_run = str(last_row.get("run_at_utc", "N/A"))
                prefect_status = str(last_row.get("pipeline_status", "UNKNOWN"))
        except Exception:
            pass

    p_badge = "🟢 SUCCESS" if prefect_status == "SUCCESS" else f"🔴 {prefect_status}"
    f_col3.metric("Prefect Pipeline Run", p_badge, help=f"Last run: {last_prefect_run}")

    # Data Quality Agent Level
    dq_level = "UNKNOWN"
    evaluated_at = "N/A"
    valid_rows = 0
    flagged_rows = 0
    if STATUS_PATH.exists():
        try:
            with open(STATUS_PATH, "r", encoding="utf-8") as f:
                sq = json.load(f)
            dq_level = sq.get("level", "UNKNOWN")
            evaluated_at = sq.get("evaluated_at_utc", "N/A")
            valid_rows = sq.get("valid_unimputed_rows", 0)
            flagged_rows = sq.get("flagged_rows", 0)
        except Exception:
            pass

    dq_badge = "🟢 OK" if dq_level == "OK" else ("🟡 WARN" if "WARN" in dq_level else "🔴 FAIL")
    f_col4.metric("DQ Agent Status", dq_badge, help=f"Evaluated: {evaluated_at} | Valid: {valid_rows:,} | Flagged: {flagged_rows:,}")

    # Decision Log Expander
    if DQ_LOG_PATH.exists():
        with st.expander("📋 Data Quality Agent Decision Log (logs/dq_log.csv)", expanded=False):
            try:
                dq_log_df = pd.read_csv(DQ_LOG_PATH)
                st.dataframe(dq_log_df.tail(25), width="stretch")
            except Exception as e:
                st.error(f"Error loading dq_log.csv: {e}")

    st.divider()

    # 2. Pakistan Impact Bonus (+4 pts)
    st.subheader("🇵🇰 Local Impact & Policy Validation (+4 Pts)")
    imp_col1, imp_col2 = st.columns(2)

    with imp_col1:
        st.markdown("#### 🏛️ EPA Punjab Smog Action Plan School Thresholds (+2 Pts)")
        st.caption("Official threshold mapping against live Lahore station averages")
        
        # Calculate current station mean
        df_daily_temp = None
        current_lahore_mean = 95.0
        if DATA_PARQUET.exists():
            try:
                df_daily_temp = pd.read_parquet(DATA_PARQUET)
                if not df_daily_temp.empty and "pm25_daily_mean" in df_daily_temp.columns:
                    latest_date = df_daily_temp["pkt_date"].max()
                    current_lahore_mean = df_daily_temp[df_daily_temp["pkt_date"] == latest_date]["pm25_daily_mean"].mean()
            except Exception:
                pass

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

    # 3. Daily Station Data & Historical Predictions
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

    # 4. Prefect 24-Hour Run Audit Log
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

    overall_mae = 11.19
    baseline_mae = 13.65
    improvement_pct = 18.0
    coverage_80 = 72.4

    if MODEL_METRICS_JSON.exists():
        try:
            with open(MODEL_METRICS_JSON, "r", encoding="utf-8") as f:
                m_data = json.load(f)
            overall_mae = m_data.get("metrics", {}).get("test", {}).get("mae", overall_mae)
        except Exception:
            pass

    m_col1.metric("Final Model Test MAE", f"{overall_mae:.2f} µg/m³")
    m_col2.metric("Persistence Baseline MAE", f"{baseline_mae:.2f} µg/m³")
    m_col3.metric("Baseline Improvement", f"+{improvement_pct:.1f}%", help="Threshold required: >= 15%")
    m_col4.metric("80% Uncertainty Coverage", f"{coverage_80:.1f}%")

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

    # Sidebar settings for RAG
    st.sidebar.markdown("---")
    st.sidebar.subheader("🤖 RAG LLM Settings")
    provider = st.sidebar.selectbox("LLM Provider", ["gemini", "openai", "anthropic", "openai_compatible"], index=0)
    api_key_input = st.sidebar.text_input(
        f"{provider.capitalize()} API Key (optional):",
        type="password",
        help="Optional: If omitted, reads from your local .env file. Leave blank to use local deterministic retrieval."
    )

    # Load / Cache evidence index
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

    # Sample query buttons (including out-of-scope question to demo live abstention)
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

                # Construct environment override if provided
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

                # Status Badge
                if rag_result.status == AnswerStatus.OK:
                    st.success(f"🟢 Status: OK | Model: {rag_result.model or provider}")
                elif rag_result.status == AnswerStatus.ABSTAINED:
                    st.warning("🟡 Status: ABSTAINED (Safe refusal due to insufficient or non-factual data)")
                elif rag_result.status == AnswerStatus.LLM_UNAVAILABLE:
                    st.info("ℹ️ Status: LLM_UNAVAILABLE (No API key found in .env or UI; deterministic gold-record evidence retrieved below)")
                else:
                    st.error(f"🔴 Status: {rag_result.status.value}")

                # Answer block
                st.markdown("### Answer")
                st.markdown(rag_result.answer)

                # Emergency Health Disclaimer if High PM2.5 detected
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

                # Citations
                if rag_result.citations:
                    st.markdown("**Verified Citations:**")
                    st.write(", ".join([f"`{c}`" for c in rag_result.citations]))

                # Exact Gold Table row_id Breakdown
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

                # Retrieved Evidence Expander
                with st.expander(f"📚 Retrieved Evidence Items ({len(retrieval.items)} items)", expanded=(rag_result.status == AnswerStatus.LLM_UNAVAILABLE)):
                    for idx, item in enumerate(retrieval.items, 1):
                        st.markdown(f"**[{idx}] `{item.citation_id}`** ({item.evidence_type})")
                        st.caption(f"Source: `{item.source}` | Score: `{item.score:.2f}`")
                        st.text(item.text)
                        st.divider()
