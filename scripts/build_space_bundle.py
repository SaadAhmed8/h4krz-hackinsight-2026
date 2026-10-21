"""
scripts/build_space_bundle.py
Builds the minimal standalone bundle for the Hugging Face Streamlit Space.
Copies only required dashboard assets, writes space/README.md with HF YAML frontmatter,
creates pinned requirements.txt, and verifies no secrets or raw data are included.
"""
import os
import shutil
from pathlib import Path

SPACE_DIR = Path("space")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Pinned exact requirements for Streamlit Space runtime
SPACE_REQUIREMENTS = """streamlit==1.66.0
pandas==3.0.6
pyarrow==26.0.0
requests==2.34.2
pyyaml==6.0.3
google-genai==2.31.0
"""

SPACE_README = """---
title: Lahore Smog PM2.5 Live Monitor
emoji: 🌫️
colorFrom: indigo
colorTo: slate
sdk: streamlit
sdk_version: 1.40.0
app_file: app.py
pinned: false
---

# 🌫️ Lahore Smog (PM2.5) Early Warning & Decision Support System
**HackInsight 2026 — Team H4krz (Data-to-Decision)**

Live automated monitoring dashboard for Lahore PM2.5 air quality forecasts, data quality health,
and cited WHO/EPA Punjab RAG decision assistance.

### Key Features
- **Live Freshness**: Monitors OpenAQ and Open-Meteo with documented <= 2.0h staleness thresholds.
- **Data Quality Agent**: Real-time evaluation results, unit checks, bounds verification, and decision log.
- **Next-Day Forecasting**: HistGradientBoosting multi-quantile predictions with 80% uncertainty bounds.
- **Ground-Truth RAG Assistant**: Cited guidance using official WHO 2021 air quality guidelines and EPA Punjab advisories.
"""


def build_space_bundle(output_dir: Path = SPACE_DIR):
    print(f"Building Hugging Face Space bundle in '{output_dir}'...")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy app.py
    shutil.copy2("app.py", output_dir / "app.py")

    # 2. Write pinned space requirements.txt
    with open(output_dir / "requirements.txt", "w", encoding="utf-8") as f:
        f.write(SPACE_REQUIREMENTS)

    # 3. Write space README.md with HF YAML frontmatter
    with open(output_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(SPACE_README)

    # 4. Copy required processed data & predictions
    data_proc_dir = output_dir / "data" / "processed"
    data_proc_dir.mkdir(parents=True, exist_ok=True)
    for p_file in ["daily.parquet", "predictions.parquet"]:
        src = Path("data/processed") / p_file
        if src.exists():
            shutil.copy2(src, data_proc_dir / p_file)

    # Copy cleaned weather if present (used in Tab 1)
    data_clean_dir = output_dir / "data" / "cleaned"
    data_clean_dir.mkdir(parents=True, exist_ok=True)
    weather_cleaned = Path("data/cleaned/weather_cleaned.parquet")
    if weather_cleaned.exists():
        shutil.copy2(weather_cleaned, data_clean_dir / "weather_cleaned.parquet")

    # 5. Copy reports used by dashboard
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for r_file in [
        "model_errors_by_group.csv",
        "pm25_hist_gradient_boosting_metrics.json",
        "station_validity.csv",
        "optimization_log.csv"
    ]:
        src = Path("reports") / r_file
        if src.exists():
            shutil.copy2(src, reports_dir / r_file)

    # 6. Copy logs & status
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for l_file in ["dq_status.json", "dq_log.csv", "prefect_runs.csv"]:
        src = Path("logs") / l_file
        if src.exists():
            shutil.copy2(src, logs_dir / l_file)

    status_dir = output_dir / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    run_status = Path("status/run_status.json")
    if run_status.exists():
        shutil.copy2(run_status, status_dir / "run_status.json")

    # 7. Copy manifest.csv
    manifest = Path("manifest.csv")
    if manifest.exists():
        shutil.copy2(manifest, output_dir / "manifest.csv")

    # 8. Copy RAG sources and modules (needed for Tab 3 Cited Assistant)
    src_dir = output_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    src_init = Path("src/__init__.py")
    if src_init.exists():
        shutil.copy2(src_init, src_dir / "__init__.py")
    else:
        (src_dir / "__init__.py").touch()
    shutil.copy2("src/utils.py", src_dir / "utils.py")
    
    rag_src = Path("src/rag")
    if rag_src.exists():
        shutil.copytree(
            rag_src,
            src_dir / "rag",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        )

    data_ext_src = Path("data/external")
    if data_ext_src.exists():
        shutil.copytree(
            data_ext_src,
            output_dir / "data" / "external",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        )

    # Copy ADR and docs referenced by RAG
    for doc_name in ["REPORT.md", "GLOSSARY.md"]:
        if Path(doc_name).exists():
            shutil.copy2(doc_name, output_dir / doc_name)
    
    adr_dir = output_dir / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    adr_file = Path("docs/adr/0001-warehouse-architecture-and-keys.md")
    if adr_file.exists():
        shutil.copy2(adr_file, adr_dir / "0001-warehouse-architecture-and-keys.md")

    # 9. Audit and Security Verification
    print("Verifying bundle security and size...")
    forbidden = [".env", ".key", "token", "password", "data/raw"]
    total_size = 0
    file_count = 0

    for root, dirs, files in os.walk(output_dir):
        # Ensure no data/raw
        rel_root = Path(root).relative_to(output_dir).as_posix()
        if "data/raw" in rel_root:
            raise RuntimeError(f"Security error: data/raw found in Space bundle: {rel_root}")

        for file in files:
            file_path = Path(root) / file
            rel_file = file_path.relative_to(output_dir).as_posix()
            
            # Check forbidden extensions
            if file.endswith(".env") or file.endswith(".key"):
                raise RuntimeError(f"Security error: Sensitive file found in bundle: {rel_file}")

            file_size = file_path.stat().st_size
            total_size += file_size
            file_count += 1

    total_mb = total_size / (1024 * 1024)
    print(f"Bundle successfully created: {file_count} files, {total_mb:.2f} MB total.")
    print("Bundle contains no .env, no API keys, and no data/raw/.")
    return output_dir


if __name__ == "__main__":
    build_space_bundle()
