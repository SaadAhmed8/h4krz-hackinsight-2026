# tests/test_dq_agent.py
import json
from datetime import datetime, timezone, timedelta
# pyrefly: ignore[missing-import]
import numpy as np
import pandas as pd
import pytest

from src.dq_schema import ContractError
from src.dq_agent import run_dq_agent, build_processed_daily_table


def _make_base_df(hours: int = 24, start_str: str = "2026-10-18 00:00:00+00:00") -> pd.DataFrame:
    ts = pd.date_range(start_str, periods=hours, freq="1h")
    pm25 = 50.0 + 10.0 * np.sin(np.arange(hours))
    return pd.DataFrame(
        {
            "station_id": "lahore_model_town",
            "ts_utc": ts,
            "pm25": pm25,
            "source": "openaq",
            "fetched_at_utc": ts + pd.Timedelta(minutes=5),
        }
    )


def _run(df, tmp_path, now_utc=None):
    return run_dq_agent(
        df,
        reference_now_utc=now_utc,
        log_path=tmp_path / "dq_log.csv",
        status_path=tmp_path / "dq_status.json",
    )


def test_clean_data_ok(tmp_path):
    df = _make_base_df(24)
    out, status = _run(df, tmp_path, df["ts_utc"].max() + timedelta(hours=1))
    assert status["level"] == "OK"
    assert status["valid_unimputed_rows"] == 24
    assert status["imputed_rows"] == 0
    assert (out["dq_flags"] == "").all()


def test_rejects_missing_columns(tmp_path):
    df = _make_base_df(10).drop(columns=["pm25"])
    with pytest.raises(ContractError, match="Missing required columns"):
        _run(df, tmp_path)


def test_rejects_naive_timestamps(tmp_path):
    df = _make_base_df(10)
    df["ts_utc"] = df["ts_utc"].dt.tz_localize(None)
    with pytest.raises(ContractError, match="timezone-naive"):
        _run(df, tmp_path)


def test_pkt_to_utc_conversion_no_shift(tmp_path):
    # 2026-10-18 05:00 PKT == 2026-10-18 00:00 UTC
    ts_pkt = pd.date_range("2026-10-18 05:00:00", periods=10, freq="1h", tz="Asia/Karachi")
    df = pd.DataFrame(
        {
            "station_id": "hawanama_iqbal_town",  # No RH or temp_c (Hawanama case)
            "ts_utc": ts_pkt,
            "pm25": np.linspace(30, 60, 10),
            "source": "openaq",
        }
    )
    out, status = _run(df, tmp_path, datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc))
    assert str(out["ts_utc"].dt.tz) == "UTC"
    assert out["ts_utc"].min() == pd.Timestamp("2026-10-18 00:00:00+00:00")
    assert status["level"] == "OK"


def test_duplicate_station_hour_keeps_latest_fetch(tmp_path):
    df = _make_base_df(10)
    dup_row = df.iloc[[3]].copy()
    dup_row["pm25"] = 99.9
    dup_row["fetched_at_utc"] = dup_row["fetched_at_utc"] + pd.Timedelta(minutes=20)
    df_with_dup = pd.concat([df, dup_row], ignore_index=True)

    out, status = _run(df_with_dup, tmp_path, df["ts_utc"].max() + timedelta(hours=1))
    assert len(out) == 10
    assert out.loc[out["ts_utc"] == dup_row["ts_utc"].iloc[0], "pm25_dq"].iloc[0] == 99.9


def test_impossible_values_fixed_to_nan(tmp_path):
    df = _make_base_df(12)
    df.loc[2, "pm25"] = -15.0
    df.loc[5, "pm25"] = 1500.0
    df["rh"] = 50.0
    df.loc[4, "rh"] = 120.0

    out, status = _run(df, tmp_path, df["ts_utc"].max() + timedelta(hours=1))
    assert bool(out.loc[2, "is_imputed"]) is True
    assert "IMPOSSIBLE_PM25" in out.loc[2, "dq_flags"]
    assert np.isnan(out.loc[4, "rh"])
    assert status["level"] == "WARN"


def test_stuck_sensor_flagged_and_masked(tmp_path):
    df = _make_base_df(24)
    df.loc[5:10, "pm25"] = 88.88
    out, status = _run(df, tmp_path, df["ts_utc"].max() + timedelta(hours=1))
    assert out.loc[5:10, "pm25_dq"].isna().all()
    assert out.loc[5:10, "valid_obs"].eq(False).all()
    assert out.loc[5:10, "dq_flags"].str.contains("STUCK_SENSOR").all()


def test_short_and_long_gaps(tmp_path):
    df = _make_base_df(24)
    df.loc[3:4, "pm25"] = np.nan
    df.loc[12:15, "pm25"] = np.nan

    out, status = _run(df, tmp_path, df["ts_utc"].max() + timedelta(hours=1))
    assert out.loc[3:4, "pm25_dq"].notna().all()
    assert out.loc[3:4, "is_imputed"].eq(True).all()
    assert out.loc[3:4, "valid_obs"].eq(False).all()

    assert out.loc[12:15, "pm25_dq"].isna().all()
    assert out.loc[12:15, "dq_flags"].str.contains("LONG_GAP_MISSING").all()


def test_stale_source_triggers_fail(tmp_path):
    df = _make_base_df(12)
    out, status = _run(df, tmp_path, df["ts_utc"].max() + timedelta(hours=5))
    assert status["level"] == "FAIL"
    assert len(status["stale_sources"]) == 1

    saved_status = json.loads((tmp_path / "dq_status.json").read_text())
    assert saved_status["level"] == "FAIL"
    log_df = pd.read_csv(tmp_path / "dq_log.csv")
    assert any(r in log_df["rule"].values for r in ("STALE_SOURCE", "STALE_STATION"))


def test_processed_daily_18_hour_rule(tmp_path):
    # 48 hours starting midnight PKT (= 19:00 UTC previous day)
    # Day 1: 2026-10-18 PKT (24h), Day 2: 2026-10-19 PKT (24h)
    df = _make_base_df(48, start_str="2026-10-17 19:00:00+00:00")
    # Set reference_now_utc into 2026-10-20 PKT (e.g. 2026-10-19 20:00 UTC) so Day 1 & Day 2 are completed
    ref_now = pd.Timestamp("2026-10-19 20:00:00+00:00").to_pydatetime()
    dq_df, _ = _run(df, tmp_path, ref_now)
    daily = build_processed_daily_table(dq_df, reference_now_utc=ref_now)
    assert len(daily) == 2
    assert daily.iloc[0]["n_valid_hours"] == 24
    assert np.isclose(daily.iloc[0]["target_next_day_pm25"], daily.iloc[1]["pm25_mean"])
    assert np.isnan(daily.iloc[1]["target_next_day_pm25"])


def test_processed_daily_drops_days_below_18_valid_hours(tmp_path):
    df = _make_base_df(48, start_str="2026-10-17 19:00:00+00:00")
    ref_now = pd.Timestamp("2026-10-19 20:00:00+00:00").to_pydatetime()
    # Knock out 7 hours on day 2 (long gap -> missing, not imputed) => 17 valid hours
    df.loc[30:36, "pm25"] = np.nan
    dq_df, _ = _run(df, tmp_path, ref_now)
    daily = build_processed_daily_table(dq_df, reference_now_utc=ref_now)
    assert len(daily) == 1
    assert np.isnan(daily.iloc[0]["target_next_day_pm25"])
