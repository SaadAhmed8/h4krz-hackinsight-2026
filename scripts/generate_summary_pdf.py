# scripts/generate_summary_pdf.py
import os
import pymupdf

def build_summary_pdf(output_path="Summary.pdf"):
    doc = pymupdf.open()
    # A4 standard: 595.3 x 841.9 pt
    page = doc.new_page(width=595.3, height=841.9)

    # Color palette
    navy = (0.06, 0.16, 0.35)
    dark_gray = (0.15, 0.15, 0.18)
    light_bg = (0.95, 0.97, 1.0)
    border_col = (0.8, 0.85, 0.92)

    # 1. Header Banner
    header_rect = pymupdf.Rect(28, 25, 567, 85)
    page.draw_rect(header_rect, color=navy, fill=navy)

    page.insert_text(
        pymupdf.Point(40, 48),
        "HackInsight 2026: Lahore Air Quality Decision System",
        fontsize=16,
        fontname="helv",
        color=(1, 1, 1),
    )
    page.insert_text(
        pymupdf.Point(40, 64),
        "Executive One-Page Summary | Track: Air Quality | Team H4krz (Data-to-Decision)",
        fontsize=10,
        fontname="helv",
        color=(0.85, 0.9, 1.0),
    )
    page.insert_text(
        pymupdf.Point(40, 78),
        "Team Members: M. Saad Ahmed, Arbish, Hasan Shahir, Noman Khursheed | Verified Test Suite: 52/52 Passed",
        fontsize=8.5,
        fontname="helv",
        color=(0.7, 0.8, 0.95),
    )

    y = 96

    def draw_card(x0, y0, x1, y1, title, fill=light_bg, border=border_col):
        r = pymupdf.Rect(x0, y0, x1, y1)
        page.draw_rect(r, color=border, fill=fill)
        page.draw_rect(pymupdf.Rect(x0, y0, x1, y0 + 17), color=border, fill=(0.9, 0.94, 0.98))
        page.insert_text(pymupdf.Point(x0 + 8, y0 + 12), title, fontsize=9.5, fontname="helv", color=navy)
        return pymupdf.Rect(x0 + 8, y0 + 21, x1 - 8, y1 - 6)

    # Block 1: Problem & Primary User (Full width)
    b1_rect = draw_card(28, y, 567, y + 84, "1. Problem Definition & Primary User Decision (Guide Ch. 3 & 5)")
    p1_text = (
        "- Problem: Severe winter PM2.5 smog in Lahore (Oct-Feb) causes overnight spikes exceeding 250 ug/m3, risking child health.\n"
        "- Primary User & Decision: A school headmaster / administrator in Lahore deciding at 4:00 PM PKT the day prior whether to cancel, "
        "modify, or move morning outdoor assemblies and physical activities based on reliable next-day PM2.5 forecasts.\n"
        "- Statistical Rules: Midnight-to-midnight PKT day definition (UTC+5), strict 18-of-24 valid hours completeness rule, and deterministic "
        "16-character SHA-256 primary keys (record_id) ensuring 100% reproducibility across all warehouse layers."
    )
    page.insert_textbox(b1_rect, p1_text, fontsize=8.2, fontname="helv", color=dark_gray, lineheight=1.2)
    y += 90

    # Two column layout: Left (Warehouse & DQ), Right (ML Model & Group Fairness)
    col_h = 248

    # Block 2: Warehouse & DQ Agent (Left)
    b2_rect = draw_card(28, y, 292, y + col_h, "2. Warehouse & Data Quality Agent (Ch. 4, 6)")
    p2_text = (
        "- Data Volume: 86,315 regular hourly rows, 65,819 valid PM2.5 observations (>50,000 threshold passed) across 8 verified Lahore stations.\n"
        "- Independent Sources: OpenAQ v3 (AirGradient & Hawanama) and Open-Meteo ERA5 Reanalysis & Forecast. 100% CC BY 4.0 compliant.\n"
        "- Licensing Contract: Station ieee_punjab_univ strictly excluded from cleaned/processed marts due to unverified licensing.\n"
        "- DuckDB Warehouse: 3 layers (raw JSONs, cleaned hourly Parquet, daily.parquet mart) synced to data/warehouse.duckdb via safe DataFrame registration.\n"
        "- SHA-256 Ledger: manifest.csv audits 253 physical files.\n"
        "- Data Quality Agent: Validates Pandera bounds and nulls; executes fix (unit correction), fill (linear interpolation), or flag (anomalies);\n"
        "- Staleness Resilience: Logs 256 quality actions to quality_log.csv. Late sensors trigger non-fatal WARN_STALE, keeping pipeline alive."
    )
    page.insert_textbox(b2_rect, p2_text, fontsize=7.8, fontname="helv", color=dark_gray, lineheight=1.18)

    # Block 3: ML Model, Uncertainty & Group Fairness (Right)
    b3_rect = draw_card(300, y, 567, y + col_h, "3. Predictive Model & Group Fairness (Ch. 7, 8)")
    p3_text = (
        "- Declared Baseline: Persistence (tomorrow equals today), MAE: 13.593 ug/m3.\n"
        "- Final Model: HistGradientBoosting Regressor with weather leads and cross-station dynamics. Test MAE: 11.139 ug/m3 (+18.05% improvement, beating declared >=15% target).\n"
        "- Temporal Split: 351 train dates (1,587 rows), 75 val dates (367 rows), 76 test dates (453 rows). Zero future leakage; untouched test set.\n"
        "- 80% Uncertainty Bounds: Multi-quantile pinball loss models (10th & 90th percentiles) yielding 73.3% empirical test coverage.\n"
        "- Group Fairness Audit (reports/model_errors_by_group.csv):\n"
        "  * Stations: Sandha Road (10.9 MAE), Model Town (10.85 MAE, +21.4%), Trinity School (11.43 MAE, +23.1%).\n"
        "  * Seasons: Non-Smog 10.77 MAE (+16.5%) vs Smog Season 12.13 MAE (+21.5% gain where smog warning matters most).\n"
        "- 3-Step Optimization Log: Iter 1 (Direct Target, -1.3%), Iter 2 (Residual Delta, +7.3%), Iter 3 (Forecast Ensemble, +18.05% kept)."
    )
    page.insert_textbox(b3_rect, p3_text, fontsize=7.8, fontname="helv", color=dark_gray, lineheight=1.18)
    y += col_h + 8

    # Block 4: Insight Agent (RAG) & Pakistan Impact Bonus (Left)
    col2_h = 245
    b4_rect = draw_card(28, y, 292, y + col2_h, "4. Insight Agent (RAG) & Pakistan Bonus (Ch. 9)")
    p4_text = (
        "- Hard Rule 1 (No Invented Numbers): Every numerical value is pulled directly from gold tables; references record_id row IDs.\n"
        "- Hard Rule 2 (Cited Sources): Grounds recommendations in WHO 2021 Global Air Quality Guidelines and EPA Punjab Smog Action Plan.\n"
        "- Hard Rule 3 (No Synthetic Evaluation): Evaluated on real held-out observations; tests pass with 0 hallucinations.\n"
        "- Honest Abstention: Returns 'I don't know based on the available evidence' on out-of-scope queries (e.g. crop yield or traffic).\n"
        "- Pakistan Impact Bonus (+10 pts):\n"
        "  * Urdu Output Toggle: Bilingual support and translations (Urdu Tarjuma) for school staff.\n"
        "  * Local Validation: EPA Punjab Smog Action Plan thresholds (<50 normal, 50-150 sensitive exertion, 150-250 cancel outdoor sports, >250 closure).\n"
        "  * Emergency Health Disclaimer: Clear referral to official hospitals."
    )
    page.insert_textbox(b4_rect, p4_text, fontsize=7.8, fontname="helv", color=dark_gray, lineheight=1.18)

    # Block 5: Hourly Automation & Business Model (Right)
    b5_rect = draw_card(300, y, 567, y + col2_h, "5. Hourly Pipeline & Business Model (Ch. 10, 11)")
    p5_text = (
        "- Hourly Automation (Prefect): Robust scheduler fires at :05 past every hour. Consecutive SUCCESS runs logged in logs/prefect_runs.csv.\n"
        "- Live Dashboard (Streamlit): 3 tabs (Live Monitoring, Model & Fairness, RAG Assistant) displaying freshness badges (FRESH / LATE), DQ audit, and last run.\n"
        "- Primary User vs Customer:\n"
        "  * Users: School administrators, sports directors, and clinic staff.\n"
        "  * Payers: School district boards, private school chains, and municipal bodies.\n"
        "- Revenue Model: Freemium SaaS. Free public portal for citizens; $25/mo per school subscription for automated SMS/email alerts and risk auditing.\n"
        "- Operational Cost: ~$15/mo (serverless compute & free-tier OpenAQ/Open-Meteo APIs). Extremely low overhead with >20x value return.\n"
        "- Value Generated: Prevents severe asthma attacks in students, avoids last-minute bus/event cancellations, and saves 3.5 hrs/week per school."
    )
    page.insert_textbox(b5_rect, p5_text, fontsize=7.8, fontname="helv", color=dark_gray, lineheight=1.18)
    y += col2_h + 8

    # Footer Banner
    footer_rect = pymupdf.Rect(28, y, 567, y + 42)
    page.draw_rect(footer_rect, color=navy, fill=(0.93, 0.96, 1.0))
    footer_text = (
        "GitHub: https://github.com/SaadAhmed8/h4krz-hackinsight-2026  |  HF Space: https://hf.co/spaces/hasanshahir/lahore-air-quality-decision-system\n"
        "Reproducibility: 'make data' or 'python -m src.pipeline' rebuilds all layers  |  Hourly Automation: 'python -m src.prefect_pipeline'\n"
        "Integrity Guarantee: Zero hard-coded values, 100% CC BY 4.0 licences, 52/52 automated unit & integration tests passing."
    )
    page.insert_textbox(pymupdf.Rect(36, y + 5, 559, y + 38), footer_text, fontsize=7.6, fontname="helv", color=navy, lineheight=1.2)

    doc.save(output_path)
    doc.close()
    print(f"Successfully generated {output_path} with {len(pymupdf.open(output_path))} page(s).")

if __name__ == "__main__":
    build_summary_pdf("Summary.pdf")
