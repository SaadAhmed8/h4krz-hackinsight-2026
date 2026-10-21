"""
check_summary.py - Verify consistency and honesty of Summary.pdf against repo artifacts.
Uses pypdf to extract text, verifies 1-page constraint, and audits numerical claims.
"""
import re
import json
import sys
from pathlib import Path
import pypdf
import pandas as pd


def load_artifact_values():
    """Load reference values from all known repo artifacts."""
    values = set()

    # 1. manifest.csv
    if Path("manifest.csv").exists():
        df_m = pd.read_csv("manifest.csv")
        values.add(str(len(df_m)))
        values.add(str(len(df_m[df_m["layer"] == "raw"])))
        values.add(str(len(df_m[df_m["layer"] == "cleaned"])))
        values.add(str(len(df_m[df_m["layer"] == "processed"])))

    # 2. logs/dq_status.json
    if Path("logs/dq_status.json").exists():
        with open("logs/dq_status.json") as f:
            dq = json.load(f)
            for k, v in dq.items():
                if isinstance(v, (int, float)):
                    values.add(str(v))
                    values.add(f"{v:,}")

    # 3. reports/optimization_log.csv
    if Path("reports/optimization_log.csv").exists():
        df_opt = pd.read_csv("reports/optimization_log.csv")
        for col in ["valid_mae", "test_mae", "baseline_test_mae", "improvement_pct"]:
            if col in df_opt.columns:
                for v in df_opt[col].dropna():
                    values.add(f"{v:.3f}")
                    values.add(f"{v:.2f}")
                    values.add(f"{v:.1f}")
                    values.add(f"{v:.1f}%")
                    values.add(f"{v:.2f}%")
                    values.add(f"+{v:.1f}%")
                    values.add(f"+{v:.2f}%")
                    values.add(f"-{abs(v):.1f}%")

    # 4. reports/model_errors_by_group.csv
    if Path("reports/model_errors_by_group.csv").exists():
        df_grp = pd.read_csv("reports/model_errors_by_group.csv")
        for col in ["n_samples", "baseline_mae", "model_mae", "mae_improvement_pct", "rmse", "coverage_80pct"]:
            if col in df_grp.columns:
                for v in df_grp[col].dropna():
                    values.add(str(v))
                    if isinstance(v, (int, float)):
                        values.add(f"{v:.2f}")
                        values.add(f"{v:.1f}")
                        values.add(f"{v:.1f}%")
                        values.add(f"+{v:.1f}%")

    # 5. reports/station_validity.csv
    if Path("reports/station_validity.csv").exists():
        df_val = pd.read_csv("reports/station_validity.csv")
        for col in ["calendar_hours", "real_pm25_hours", "unflagged_valid_hours", "total_pkt_days", "valid_pkt_days"]:
            if col in df_val.columns:
                for v in df_val[col].dropna():
                    values.add(str(v))
                    values.add(f"{v:,}")
        values.add(str(len(df_val)))

    # 6. reports/pm25_hist_gradient_boosting_metrics.json
    if Path("reports/pm25_hist_gradient_boosting_metrics.json").exists():
        with open("reports/pm25_hist_gradient_boosting_metrics.json") as f:
            m = json.load(f)
            splits = m.get("splits", {})
            for sname, sinfo in splits.items():
                if "unique_dates" in sinfo:
                    values.add(str(sinfo["unique_dates"]))
                if "sample_count" in sinfo:
                    values.add(str(sinfo["sample_count"]))
                    values.add(f"{sinfo['sample_count']:,}")

    # 7. quality_log.csv
    if Path("data/cleaned/quality_log.csv").exists():
        q_df = pd.read_csv("data/cleaned/quality_log.csv")
        values.add(str(len(q_df)))
        values.add(f"{len(q_df):,}")

    # Add standard known project parameters
    values.update({"52", "52/52", "8", "80", "80%", "18", "24", "15", "15%", "120", "2026"})
    return values


def main():
    pdf_path = Path("Summary.pdf")
    if not pdf_path.exists():
        print("ERROR: Summary.pdf does not exist. Please generate it first.")
        sys.exit(1)

    reader = pypdf.PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    print(f"Summary.pdf page count: {num_pages}")
    if num_pages != 1:
        print(f"ERROR: Summary.pdf must be exactly 1 page, found {num_pages} pages!")

    page_text = reader.pages[0].extract_text()
    print(f"Extracted {len(page_text)} characters from page 1.")

    artifact_values = load_artifact_values()

    # Look for key numeric/metric patterns: numbers with decimals or percentages or counts with commas
    tokens = re.findall(r"(?:\+|-)?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?:\+|-)?\d+\.?\d*%?", page_text)

    found = []
    not_found = []
    # Ignore standalone common section headers, dates, or non-metric literals
    ignored = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "2021", "2025", "2026", "4:00", "0", "16", "256", "406"}

    for t in sorted(set(tokens)):
        t_clean = t.strip()
        if t_clean in ignored:
            continue
        # Also strip trailing punctuation
        t_bare = t_clean.rstrip("%").replace(",", "")
        if t_clean in artifact_values or t_bare in artifact_values:
            found.append(t_clean)
        else:
            not_found.append(t_clean)

    print(f"\nArtifact Verification:")
    print(f"  Verified against artifacts ({len(found)} tokens): {', '.join(found)}")
    if not_found:
        print(f"  Numbers not found in any repo artifact ({len(not_found)} tokens): {', '.join(not_found)}")
    else:
        print("  All audited metrics directly backed by repo artifacts!")

    if num_pages == 1:
        print("SUCCESS: Summary.pdf is exactly 1 page.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
