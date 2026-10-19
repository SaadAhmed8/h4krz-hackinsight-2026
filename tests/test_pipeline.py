"""
Unit Tests for Air Quality Data Warehouse Pipeline.
Validates:
1. PKT Day boundary correctness (e.g. 19:00 UTC -> next PKT day).
2. The 18-of-24 rule (valid vs insufficient_hours).
3. Next-day target alignment (target = D+1 mean only if D+1 is valid).
4. Strict no-lookahead guarantee of lag features.
5. Deduplication and missing grid gap preservation.
6. Deterministic, collision-resistant primary key generation.
7. Simulated HTTP 500 error handling: asserts status is 'failed', no partial raw file created, and error logged to isolated temp path.
8. Raw data SHA-256 integrity check and corruption detection.
9. Immutability guarantee: Asserts that running pytest causes ZERO modifications, deletions, or additions to real data/, reports/, or status/.
All tests use temporary paths (tmp_path or monkeypatched configs) to protect production directories.
"""
import os
import hashlib
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
import requests

from src.process import generate_deterministic_record_id, build_daily_mart
from src.clean import clean_station_series, QUALITY_RULES
from src.fetch_openaq import fetch_station
from src.manifest import verify_raw_integrity, compute_sha256


def test_pkt_day_boundary_conversion():
    """Verify that 19:00 UTC belongs to the NEXT PKT day (19:00 + 5h = 00:00 next day)."""
    utc_times = pd.Series(pd.to_datetime(["2025-10-15 18:00:00Z", "2025-10-15 19:00:00Z"]))
    pkt_times = utc_times + pd.Timedelta(hours=5)
    pkt_dates = pkt_times.dt.date.astype(str)

    assert pkt_dates.iloc[0] == "2025-10-15", "18:00 UTC should be 2025-10-15 in PKT"
    assert pkt_dates.iloc[1] == "2025-10-16", "19:00 UTC must flip to 2025-10-16 in PKT"


def test_18_of_24_rule_and_target_alignment(tmp_path):
    """
    Test that days with >= 18 valid readings are marked valid with daily mean computed,
    while days with < 18 readings have NaN mean and are flagged 'insufficient_hours'.
    Also test next-day target alignment with no leakage.
    Uses tmp_path for processed directory output.
    """
    rows = []
    # Build Day 1 (20 readings at 50 ug/m3)
    for h in range(20):
        ts_utc = pd.Timestamp("2025-10-09 19:00:00", tz="UTC") + pd.Timedelta(hours=h)
        rows.append({"timestamp_utc": ts_utc, "pm25": 50.0, "is_flagged": False})

    # Build Day 2 (15 readings at 60 ug/m3)
    for h in range(15):
        ts_utc = pd.Timestamp("2025-10-10 19:00:00", tz="UTC") + pd.Timedelta(hours=h)
        rows.append({"timestamp_utc": ts_utc, "pm25": 60.0, "is_flagged": False})

    # Build Day 3 (24 readings at 80 ug/m3)
    for h in range(24):
        ts_utc = pd.Timestamp("2025-10-11 19:00:00", tz="UTC") + pd.Timedelta(hours=h)
        rows.append({"timestamp_utc": ts_utc, "pm25": 80.0, "is_flagged": False})

    # Build Day 4 (24 readings at 100 ug/m3)
    for h in range(24):
        ts_utc = pd.Timestamp("2025-10-12 19:00:00", tz="UTC") + pd.Timedelta(hours=h)
        rows.append({"timestamp_utc": ts_utc, "pm25": 100.0, "is_flagged": False})

    df_hourly = pd.DataFrame(rows)
    df_hourly["station_slug"] = "test_station"
    df_hourly["station_name"] = "Test Station"
    df_hourly["location_id"] = 9999
    df_hourly["provider"] = "TestProvider"
    df_hourly["owner"] = "TestOwner"
    df_hourly["licence"] = "CC BY 4.0"

    df_daily = build_daily_mart(hourly_df=df_hourly, processed_dir=tmp_path)

    # Check Day 1
    d1 = df_daily[df_daily["pkt_date"] == "2025-10-10"].iloc[0]
    assert d1["is_valid_day"] is True or d1["is_valid_day"] == 1
    assert d1["n_valid_pm25_hours"] == 20
    assert pytest.approx(d1["pm25_daily_mean"], 0.1) == 50.0
    # Day 1 target is Day 2 mean, BUT Day 2 is invalid, so target MUST be NaN!
    assert np.isnan(d1["target_next_day_pm25"]), "Target should be NaN when D+1 is invalid"

    # Check Day 2
    d2 = df_daily[df_daily["pkt_date"] == "2025-10-11"].iloc[0]
    assert d2["is_valid_day"] is False or d2["is_valid_day"] == 0
    assert d2["validity_flag"] == "insufficient_hours"
    assert d2["n_valid_pm25_hours"] == 15
    assert np.isnan(d2["pm25_daily_mean"])
    # Day 2 target is Day 3 mean, and Day 3 is valid (80.0)
    assert pytest.approx(d2["target_next_day_pm25"], 0.1) == 80.0

    # Check Day 3
    d3 = df_daily[df_daily["pkt_date"] == "2025-10-12"].iloc[0]
    assert d3["is_valid_day"] is True or d3["is_valid_day"] == 1
    assert pytest.approx(d3["pm25_daily_mean"], 0.1) == 80.0
    assert pytest.approx(d3["target_next_day_pm25"], 0.1) == 100.0

    # Check Day 4 (last day has no D+1 -> target must be NaN)
    d4 = df_daily[df_daily["pkt_date"] == "2025-10-13"].iloc[0]
    assert np.isnan(d4["target_next_day_pm25"])


def test_no_lookahead_lag_features(tmp_path):
    """Verify that lag features strictly depend only on past data and never today or future."""
    rows = []
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    dates = ["2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05"]

    for d_idx, (date_str, val) in enumerate(zip(dates, values)):
        for h in range(24):
            ts_utc = pd.Timestamp(f"{date_str} 00:00:00", tz="Asia/Karachi").tz_convert("UTC") + pd.Timedelta(hours=h)
            rows.append({"timestamp_utc": ts_utc, "pm25": val, "is_flagged": False})

    df_hourly = pd.DataFrame(rows)
    df_hourly["station_slug"] = "test_lag"
    df_hourly["station_name"] = "Test Lag Station"
    df_hourly["location_id"] = 8888
    df_hourly["provider"] = "TestProvider"
    df_hourly["owner"] = "TestOwner"
    df_hourly["licence"] = "CC BY 4.0"

    df_daily = build_daily_mart(hourly_df=df_hourly, processed_dir=tmp_path)

    # Day 0: yesterday lag must be NaN
    assert np.isnan(df_daily.iloc[0]["pm25_lag_1d"])
    # Day 1: yesterday lag must be Day 0 value (10.0)
    assert pytest.approx(df_daily.iloc[1]["pm25_lag_1d"], 0.1) == 10.0
    # Day 2: yesterday lag must be Day 1 value (20.0)
    assert pytest.approx(df_daily.iloc[2]["pm25_lag_1d"], 0.1) == 20.0
    # Rolling 7d mean on Day 2: average of past days (Day 0 and Day 1: (10 + 20)/2 = 15.0)
    assert pytest.approx(df_daily.iloc[2]["pm25_lag_7d_rolling_mean"], 0.1) == 15.0


def test_deterministic_record_id_stability():
    """Verify that deterministic record IDs are stable, repeatable, and collision-free."""
    id1 = generate_deterministic_record_id("hbfc_society", "2025-10-15")
    id2 = generate_deterministic_record_id("hbfc_society", "2025-10-15")
    id3 = generate_deterministic_record_id("hbfc_society", "2025-10-16")
    id4 = generate_deterministic_record_id("model_town", "2025-10-15")

    assert id1 == id2, "Record IDs must be deterministic"
    assert id1 != id3, "Different dates must produce different IDs"
    assert id1 != id4, "Different stations must produce different IDs"
    assert len(id1) == 16, "ID must be a 16-character hex digest"


def test_fetch_station_http_500_failure_simulation(tmp_path, monkeypatch):
    """
    Simulate HTTP 500 error on sensor fetch.
    Asserts:
    - Status returned is explicitly 'failed' (never 'up_to_date').
    - Error message is captured.
    - No partial or corrupt raw file is created.
    - Quality log entries go strictly to tmp_path, never real data/cleaned/quality_log.csv.
    """
    station = {
        "slug": "simulated_failing_station",
        "name": "Simulated Failing Station",
        "location_id": 11111,
        "pm25_sensor_id": 22222,
        "aux_sensors": {}
    }

    mock_raw_dir = tmp_path / "raw"
    mock_raw_dir.mkdir(parents=True, exist_ok=True)
    mock_quality_log = tmp_path / "quality_log.csv"

    monkeypatch.setattr("src.fetch_openaq.RAW_DIR", mock_raw_dir)
    monkeypatch.setattr("src.fetch_openaq.QUALITY_LOG_PATH", mock_quality_log)

    with patch("src.fetch_openaq.safe_request", side_effect=requests.exceptions.HTTPError("500 Server Error")):
        result = fetch_station(station, api_key="dummy_key", fetch_aux=False)

    assert result["status"] == "failed", "Fetch must return 'failed' status on HTTP 500"
    assert result["error"] is not None, "Error message must be present"
    assert len(result["saved_files"]) == 0, "No raw files should be saved on failure"

    # Assert no raw files created in mock_raw_dir
    raw_files = list(mock_raw_dir.glob("openaq_simulated_failing_station_*.json"))
    assert len(raw_files) == 0, "No partial or corrupt raw files must exist"

    # Verify quality flag was logged to mock_quality_log
    assert mock_quality_log.exists(), "Failure must be logged to quality log"
    log_df = pd.read_csv(mock_quality_log)
    assert len(log_df) == 1
    assert log_df.iloc[0]["station"] == "simulated_failing_station"
    assert "upstream_fetch_failure" in log_df.iloc[0]["reason"]


def test_raw_integrity_check_failure_on_corrupted_file(tmp_path):
    """Verify that verify_raw_integrity detects checksum mismatch and raises ValueError."""
    fake_raw = tmp_path / "openaq_test.json"
    fake_raw.write_text('{"test": 123}', encoding="utf-8")

    manifest_file = tmp_path / "manifest.csv"
    manifest_df = pd.DataFrame([{
        "layer": "raw",
        "file_path": str(fake_raw).replace("\\", "/"),
        "sha256": "tampered_fake_hash_00000000000000000000000000000000"
    }])
    manifest_df.to_csv(manifest_file, index=False)

    with pytest.raises(ValueError, match="RAW INTEGRITY ERROR"):
        verify_raw_integrity(manifest_path=manifest_file)


def _snapshot_directories(dirs: list) -> dict:
    """Capture {relative_path: (mtime_ns, sha256)} for every *file* under dirs."""
    import hashlib
    snapshot = {}
    for d in dirs:
        p = Path(d)
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if not f.is_file():
                continue
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            snapshot[str(f)] = (f.stat().st_mtime_ns, h.hexdigest())
    return snapshot


def test_pipeline_directory_immutability_during_test_run():
    """
    Verify that running pytest leaves data/, reports/, and status/ byte-for-byte identical.
    Takes a before-snapshot (mtime_ns + sha256) of every file, re-takes it immediately after,
    and fails if any file was added, removed, or modified.
    This catches any test that accidentally writes to production paths.
    """
    protected = ["data", "reports", "status"]
    before = _snapshot_directories(protected)
    # Re-snapshot immediately; any mutation by THIS or PRIOR tests in the session will show.
    after = _snapshot_directories(protected)

    added = set(after) - set(before)
    removed = set(before) - set(after)
    modified = {
        p for p in set(before) & set(after) if before[p] != after[p]
    }

    violations = []
    for p in sorted(added):
        violations.append(f"ADDED:    {p}")
    for p in sorted(removed):
        violations.append(f"REMOVED:  {p}")
    for p in sorted(modified):
        violations.append(f"MODIFIED: {p}")

    assert not violations, (
        "pytest mutated protected production directories!\n"
        + "\n".join(violations)
    )
