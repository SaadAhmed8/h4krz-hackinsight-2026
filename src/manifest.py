"""
Manifest Generation & Integrity Ledger.
- Calculates SHA-256 hashes, exact row counts, and date bounds directly from disk.
- Preserves the original fetched_at_utc per raw file (never overwrites historical fetch timestamps).
- Records weather endpoint and weather_source.
- Provides verify_raw_integrity() to check raw files against existing manifest.csv.
"""
import sys
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd
import yaml

logger = logging.getLogger("manifest")

REPO_ROOT = Path(".")
RAW_DIR = REPO_ROOT / "data" / "raw"
CLEANED_DIR = REPO_ROOT / "data" / "cleaned"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
MANIFEST_PATH = REPO_ROOT / "manifest.csv"
CONFIG_PATH = REPO_ROOT / "config" / "stations.yaml"


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_raw_integrity(manifest_path: Path = MANIFEST_PATH) -> bool:
    """
    Verify the SHA-256 integrity of every raw file against manifest.csv.
    Fails loudly if any file has been modified or corrupted.
    """
    if not manifest_path.exists():
        logger.info("No prior manifest.csv found. Skipping pre-clean integrity check.")
        return True

    logger.info(f"Verifying raw data integrity against {manifest_path}...")
    manifest_df = pd.read_csv(manifest_path)
    raw_entries = manifest_df[manifest_df["layer"] == "raw"]

    mismatches = []
    missing = []

    for _, row in raw_entries.iterrows():
        f_path = REPO_ROOT / Path(row["file_path"])
        expected_sha = row["sha256"]

        if not f_path.exists():
            missing.append(row["file_path"])
            continue

        actual_sha = compute_sha256(f_path)
        if actual_sha != expected_sha:
            mismatches.append({
                "file_path": row["file_path"],
                "expected": expected_sha,
                "actual": actual_sha
            })

    if missing:
        err_msg = f"RAW INTEGRITY ERROR: Missing {len(missing)} raw files listed in manifest: {missing}"
        logger.error(err_msg)
        raise FileNotFoundError(err_msg)

    if mismatches:
        err_msg = f"RAW INTEGRITY ERROR: SHA-256 mismatch detected in {len(mismatches)} files! Corruption or unauthorized edit detected: {mismatches}"
        logger.error(err_msg)
        raise ValueError(err_msg)

    logger.info(f"Integrity check passed! All {len(raw_entries)} raw files match manifest SHA-256 digests.")
    return True


def inspect_raw_openaq_file(file_path: Path) -> Dict[str, Any]:
    """Extract metadata and row details from a raw OpenAQ JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    results = data.get("results", [])
    row_count = len(results)

    first_ts = None
    last_ts = None
    if results:
        timestamps = []
        for r in results:
            period = r.get("period") or {}
            dt_to = (period.get("datetimeTo") or {}).get("utc")
            if dt_to:
                timestamps.append(dt_to)
        if timestamps:
            first_ts = min(timestamps)
            last_ts = max(timestamps)

    # Use original fetched_at_utc from file metadata
    fetched_at = meta.get("fetched_at_utc")
    if not fetched_at:
        # Fallback to file creation timestamp
        fetched_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return {
        "layer": "raw",
        "file_path": str(file_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source": meta.get("source", "OpenAQ v3"),
        "station_name": meta.get("station_name"),
        "location_id": meta.get("location_id"),
        "sensor_id": meta.get("sensor_id"),
        "provider": meta.get("provider"),
        "owner": meta.get("owner"),
        "licence": meta.get("licence", "UNKNOWN"),
        "source_url": meta.get("source_url"),
        "query": meta.get("query") or (
            f"GET {meta.get('source_url')} parameter={meta.get('parameter')} "
            f"(paginated limit/page; datetime_from=last stored ts)"
        ),
        "fetched_at_utc": fetched_at,
        "rows": row_count,
        "first_timestamp_utc": first_ts,
        "last_timestamp_utc": last_ts,
        "sha256": compute_sha256(file_path)
    }


def inspect_raw_weather_file(file_path: Path) -> Dict[str, Any]:
    """Extract metadata and row details from a raw Open-Meteo weather JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    hourly = data.get("data", {}).get("hourly", {})
    times = hourly.get("time", [])
    row_count = len(times)

    first_ts = times[0] + ":00Z" if times else None
    last_ts = times[-1] + ":00Z" if times else None

    fetched_at = meta.get("fetched_at_utc")
    if not fetched_at:
        fetched_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    w_source = meta.get("weather_source", "archive")
    endpoint_url = meta.get("endpoint") or meta.get("source_url") or "https://archive-api.open-meteo.com/v1/archive"

    return {
        "layer": "raw",
        "file_path": str(file_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source": meta.get("source", f"Open-Meteo ({w_source})"),
        "station_name": "Lahore (Regional ERA5 Grid)",
        "location_id": "N/A (ERA5 Grid)",
        "sensor_id": f"N/A ({w_source})",
        "provider": "Open-Meteo",
        "owner": "Copernicus ERA5 / Open-Meteo",
        "licence": meta.get("licence", "UNKNOWN"),
        "source_url": endpoint_url,
        "query": meta.get("query") or meta.get("source_url") or endpoint_url,
        "fetched_at_utc": fetched_at,
        "rows": row_count,
        "first_timestamp_utc": first_ts,
        "last_timestamp_utc": last_ts,
        "sha256": compute_sha256(file_path)
    }


def inspect_parquet_file(file_path: Path, layer: str, existing_manifest_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """Inspect summary row for a cleaned or processed Parquet file, preserving original fetched_at_utc if present."""
    df = pd.read_parquet(file_path)
    row_count = len(df)
    
    first_ts = None
    last_ts = None
    if "timestamp_utc" in df.columns and not df.empty:
        first_ts = str(df["timestamp_utc"].min())
        last_ts = str(df["timestamp_utc"].max())
    elif "pkt_date" in df.columns and not df.empty:
        first_ts = str(df["pkt_date"].min())
        last_ts = str(df["pkt_date"].max())
    elif "date_pkt" in df.columns and not df.empty:
        first_ts = str(df["date_pkt"].min())
        last_ts = str(df["date_pkt"].max())

    st_name = df["station_name"].iloc[0] if "station_name" in df.columns and not df.empty else "All Stations / Multi"
    loc_id = df["location_id"].iloc[0] if "location_id" in df.columns and not df.empty else "All"
    provider = df["provider"].iloc[0] if "provider" in df.columns and not df.empty else "Various"
    owner = df["owner"].iloc[0] if "owner" in df.columns and not df.empty else "Various"
    licence = df["licence"].iloc[0] if "licence" in df.columns and not df.empty else "UNKNOWN"

    rel_path_str = str(file_path.relative_to(REPO_ROOT)).replace("\\", "/")
    
    # Check if this exact file was previously recorded with identical sha256 to preserve original fetched_at_utc
    current_sha = compute_sha256(file_path)
    fetched_at = None
    if existing_manifest_df is not None and not existing_manifest_df.empty:
        prior = existing_manifest_df[
            (existing_manifest_df["file_path"] == rel_path_str) & 
            (existing_manifest_df["sha256"] == current_sha)
        ]
        if not prior.empty and "fetched_at_utc" in prior.columns:
            fetched_at = prior.iloc[0]["fetched_at_utc"]

    if not fetched_at:
        fetched_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return {
        "layer": layer,
        "file_path": rel_path_str,
        "source": "OpenAQ v3 / Open-Meteo",
        "station_name": st_name,
        "location_id": loc_id,
        "sensor_id": "Summary Parquet",
        "provider": provider,
        "owner": owner,
        "licence": licence,
        "source_url": "Internal Warehouse Transform",
        "query": "N/A (derived by src/clean.py / src/process.py)",
        "fetched_at_utc": fetched_at,
        "rows": row_count,
        "first_timestamp_utc": first_ts,
        "last_timestamp_utc": last_ts,
        "sha256": current_sha
    }


def generate_manifest(output_path: Path = MANIFEST_PATH) -> pd.DataFrame:
    """Generate manifest.csv from actual files in raw, cleaned, and processed layers."""
    existing_df = None
    if output_path.exists():
        try:
            existing_df = pd.read_csv(output_path)
        except Exception:
            existing_df = None

    manifest_rows = []

    # 1. Raw layer OpenAQ files
    if RAW_DIR.exists():
        raw_openaq_files = sorted(RAW_DIR.glob("openaq_*.json"))
        for f in raw_openaq_files:
            try:
                manifest_rows.append(inspect_raw_openaq_file(f))
            except Exception as e:
                logger.error(f"Error inspecting {f.name}: {e}")

        # Raw layer weather files
        raw_weather_files = sorted(RAW_DIR.glob("weather_*.json"))
        for f in raw_weather_files:
            try:
                manifest_rows.append(inspect_raw_weather_file(f))
            except Exception as e:
                logger.error(f"Error inspecting {f.name}: {e}")

    # 2. Cleaned layer summary rows
    if CLEANED_DIR.exists():
        cleaned_files = sorted(CLEANED_DIR.glob("*.parquet"))
        for f in cleaned_files:
            try:
                manifest_rows.append(inspect_parquet_file(f, layer="cleaned", existing_manifest_df=existing_df))
            except Exception as e:
                logger.error(f"Error inspecting cleaned file {f.name}: {e}")

    # 3. Processed layer summary rows
    if PROCESSED_DIR.exists():
        processed_files = sorted(PROCESSED_DIR.glob("*.parquet"))
        for f in processed_files:
            try:
                manifest_rows.append(inspect_parquet_file(f, layer="processed", existing_manifest_df=existing_df))
            except Exception as e:
                logger.error(f"Error inspecting processed file {f.name}: {e}")

    cols = [
        "layer",
        "file_path",
        "source",
        "station_name",
        "location_id",
        "sensor_id",
        "provider",
        "owner",
        "licence",
        "source_url",
        "query",
        "fetched_at_utc",
        "rows",
        "first_timestamp_utc",
        "last_timestamp_utc",
        "sha256"
    ]

    manifest_df = pd.DataFrame(manifest_rows)
    if manifest_df.empty:
        manifest_df = pd.DataFrame(columns=cols)
    else:
        manifest_df = manifest_df[cols]

    manifest_df.to_csv(output_path, index=False)
    logger.info(f"Generated {output_path} with {len(manifest_df)} records.")
    return manifest_df


def main():
    try:
        generate_manifest()
    except Exception as e:
        logger.error(f"Manifest generation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
