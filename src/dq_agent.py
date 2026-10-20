# src/dq_agent.py
import os
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List, Union

import numpy as np
import pandas as pd
import pandera.pandas as pa

from src.dq_schema import (
    validate_contract_guards,
    CleanedLayerSchema,
    ProcessedDailySchema,
    ContractError,
    SOURCE_STALENESS_LIMITS_HOURS,
)


@dataclass
class DQConfig:
    pm25_min: float = 0.0
    pm25_max: float = 1000.0
    rh_min: float = 0.0
    rh_max: float = 100.0
    temp_min: float = -10.0
    temp_max: float = 55.0
    stuck_window_hours: int = 6
    max_interp_gap_hours: int = 2
    min_valid_hours_per_day: int = 18
    impossible_pm25_fail_ratio: float = 0.50  # Probe 17: fail if >50% values are out of bounds


def _append_flag(series: pd.Series, mask: pd.Series, flag: str) -> pd.Series:
    if not mask.any():
        return series
    out = series.copy()
    existing = out.loc[mask]
    out.loc[mask] = np.where(existing == "", flag, existing + "|" + flag)
    return out


def _atomic_write_json(data: Dict[str, Any], target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(target_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def run_dq_agent(
    df: pd.DataFrame,
    reference_now_utc: Optional[datetime] = None,
    log_path: Union[str, Path] = "logs/dq_log.csv",
    status_path: Union[str, Path] = "logs/dq_status.json",
    config: Optional[DQConfig] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    config = config or DQConfig()
    now_utc = reference_now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        raise ContractError("reference_now_utc must be timezone-aware (UTC).")
    now_utc_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Contract Guards
    work = validate_contract_guards(df, reference_now_utc=now_utc)
    log_entries: List[Dict[str, Any]] = []

    def record_log(rule: str, station_id: str, rows_affected: int, decision: str, reason: str):
        if rows_affected > 0:
            log_entries.append(
                {
                    "logged_at_utc": now_utc_str,
                    "rule": rule,
                    "station_id": str(station_id),
                    "rows_affected": int(rows_affected),
                    "decision": decision,
                    "reason": reason,
                }
            )

    # Probe 06: Explicitly log non-numeric string coercions
    if not pd.api.types.is_numeric_dtype(work["pm25"]):
        coerced = pd.to_numeric(work["pm25"], errors="coerce")
        unparseable = work["pm25"].notna() & coerced.isna()
        if unparseable.any():
            for st_id, cnt in work.loc[unparseable].groupby("station_id").size().items():
                record_log(
                    rule="NON_NUMERIC_COERCION",
                    station_id=st_id,
                    rows_affected=int(cnt),
                    decision="FIX",
                    reason="String/non-numeric PM2.5 values coerced to NaN.",
                )
        work["pm25"] = coerced
    work["pm25"] = work["pm25"].astype(float)

    # Probe 16: Log sub-hourly timestamps that require rounding
    floored_ts = work["ts_utc"].dt.floor("h")
    sub_hourly = work["ts_utc"] != floored_ts
    if sub_hourly.any():
        for st_id, cnt in work.loc[sub_hourly].groupby("station_id").size().items():
            record_log(
                rule="SUB_HOURLY_ROUNDING",
                station_id=st_id,
                rows_affected=int(cnt),
                decision="FIX",
                reason="Sub-hourly timestamps rounded down to the nearest hour.",
            )
    work["ts_utc"] = floored_ts

    # 2. Deduplicate
    if "fetched_at_utc" in work.columns:
        work = work.sort_values(["station_id", "ts_utc", "fetched_at_utc"], na_position="first")
    else:
        work = work.sort_values(["station_id", "ts_utc"])

    dup_mask = work.duplicated(subset=["station_id", "ts_utc"], keep="last")
    if dup_mask.any():
        for st_id, count in work.loc[dup_mask].groupby("station_id").size().items():
            record_log(
                rule="DUPLICATE_STATION_HOUR",
                station_id=st_id,
                rows_affected=int(count),
                decision="FIX",
                reason="Removed duplicate station-hour; kept latest fetched record.",
            )
        work = work.loc[~dup_mask].copy()

    # 3. Complete Hourly Grid
    reindexed_frames = []
    for st_id, group in work.groupby("station_id", sort=False):
        group = group.sort_values("ts_utc")
        full_idx = pd.date_range(group["ts_utc"].min(), group["ts_utc"].max(), freq="1h")
        src_val = group["source"].iloc[0]

        reindexed = group.set_index("ts_utc").reindex(full_idx)
        reindexed.index.name = "ts_utc"
        reindexed = reindexed.reset_index()
        reindexed["station_id"] = st_id
        reindexed["source"] = reindexed["source"].fillna(src_val)
        reindexed_frames.append(reindexed)

    work = pd.concat(reindexed_frames, ignore_index=True)
    work["pm25_dq"] = pd.to_numeric(work["pm25"], errors="coerce").astype(float)
    work["is_imputed"] = False
    work["dq_flags"] = ""

    # 4. Bounds Check (Probe 17)
    initial_valid_pm25_count = int(work["pm25_dq"].notna().sum())
    bad_pm25 = work["pm25_dq"].notna() & (
        (work["pm25_dq"] < config.pm25_min) | (work["pm25_dq"] > config.pm25_max)
    )
    impossible_pm25_count = int(bad_pm25.sum())

    if bad_pm25.any():
        for st_id, count in work.loc[bad_pm25].groupby("station_id").size().items():
            record_log(
                rule="IMPOSSIBLE_PM25",
                station_id=st_id,
                rows_affected=int(count),
                decision="FIX",
                reason=f"PM2.5 outside [{config.pm25_min}, {config.pm25_max}] set to NaN.",
            )
        work.loc[bad_pm25, "pm25_dq"] = np.nan
        work["dq_flags"] = _append_flag(work["dq_flags"], bad_pm25, "IMPOSSIBLE_PM25")

    if "rh" in work.columns:
        work["rh"] = pd.to_numeric(work["rh"], errors="coerce").astype(float)
        bad_rh = work["rh"].notna() & ((work["rh"] < config.rh_min) | (work["rh"] > config.rh_max))
        if bad_rh.any():
            for st_id, count in work.loc[bad_rh].groupby("station_id").size().items():
                record_log(
                    rule="IMPOSSIBLE_RH",
                    station_id=st_id,
                    rows_affected=int(count),
                    decision="FIX",
                    reason=f"RH outside [{config.rh_min}, {config.rh_max}]% set to missing.",
                )
            work.loc[bad_rh, "rh"] = np.nan
            work["dq_flags"] = _append_flag(work["dq_flags"], bad_rh, "IMPOSSIBLE_RH")

    if "temp_c" in work.columns:
        work["temp_c"] = pd.to_numeric(work["temp_c"], errors="coerce").astype(float)
        bad_temp = work["temp_c"].notna() & (
            (work["temp_c"] < config.temp_min) | (work["temp_c"] > config.temp_max)
        )
        if bad_temp.any():
            for st_id, count in work.loc[bad_temp].groupby("station_id").size().items():
                record_log(
                    rule="IMPOSSIBLE_TEMP",
                    station_id=st_id,
                    rows_affected=int(count),
                    decision="FIX",
                    reason=f"Temp outside [{config.temp_min}, {config.temp_max}] C set to missing.",
                )
            work.loc[bad_temp, "temp_c"] = np.nan
            work["dq_flags"] = _append_flag(work["dq_flags"], bad_temp, "IMPOSSIBLE_TEMP")

    # 5. Stuck Sensors & Gaps
    processed_groups = []
    for st_id, group in work.groupby("station_id", sort=False):
        g = group.sort_values("ts_utc").copy()
        s = g["pm25_dq"]

        change_or_na = (s != s.shift(1)) | s.isna()
        run_ids = change_or_na.cumsum()
        run_sizes = s.groupby(run_ids).transform("count")
        stuck_mask = s.notna() & (run_sizes >= config.stuck_window_hours)

        if stuck_mask.any():
            record_log(
                rule="STUCK_SENSOR",
                station_id=st_id,
                rows_affected=int(stuck_mask.sum()),
                decision="FLAG",
                reason=f"Stuck sensor >= {config.stuck_window_hours}h; masked.",
            )
            g.loc[stuck_mask, "pm25_dq"] = np.nan
            g["dq_flags"] = _append_flag(g["dq_flags"], stuck_mask, "STUCK_SENSOR")

        all_na = g["pm25_dq"].isna()
        is_na = all_na & (~stuck_mask)
        if is_na.any():
            na_run_id = (~all_na).cumsum()
            na_run_sizes = all_na.groupby(na_run_id).transform("sum")
            short_gap = is_na & (na_run_sizes <= config.max_interp_gap_hours)
            long_gap = is_na & (na_run_sizes > config.max_interp_gap_hours)

            interpolated = g["pm25_dq"].interpolate(
                method="linear", limit=config.max_interp_gap_hours, limit_area="inside"
            )
            filled = short_gap & interpolated.notna()
            if filled.any():
                g.loc[filled, "pm25_dq"] = interpolated.loc[filled]
                g.loc[filled, "is_imputed"] = True
                g["dq_flags"] = _append_flag(g["dq_flags"], filled, "SHORT_GAP_FILLED")
                record_log(
                    rule="SHORT_GAP_LE_2H",
                    station_id=st_id,
                    rows_affected=int(filled.sum()),
                    decision="FILL",
                    reason="Interpolated gap <= 2h.",
                )

            unfilled = long_gap | (short_gap & interpolated.isna())
            if unfilled.any():
                g["dq_flags"] = _append_flag(g["dq_flags"], unfilled, "LONG_GAP_MISSING")
                record_log(
                    rule="LONG_GAP_GT_2H",
                    station_id=st_id,
                    rows_affected=int(unfilled.sum()),
                    decision="FLAG",
                    reason="Gap > 2h left missing.",
                )

        processed_groups.append(g)

    work = pd.concat(processed_groups, ignore_index=True)
    work["is_imputed"] = work["is_imputed"].astype(bool)
    work["valid_obs"] = work["pm25_dq"].notna() & (~work["is_imputed"])

    # 6. Staleness Check: Per Station & Per Source (Probe 13 & 15)
    stale_entities: List[Dict[str, Any]] = []
    for (st_id, src), group in work.groupby(["station_id", "source"]):
        src_clean = str(src).lower().strip()
        limit_h = SOURCE_STALENESS_LIMITS_HOURS.get(src_clean, 3.0)

        valid_ts = group.loc[group["valid_obs"], "ts_utc"]
        max_ts = valid_ts.max() if not valid_ts.empty else group["ts_utc"].max()
        lag_hours = (pd.Timestamp(now_utc) - max_ts).total_seconds() / 3600.0

        if lag_hours > limit_h:
            stale_entities.append(
                {
                    "station_id": st_id,
                    "source": src,
                    "latest_ts_utc": max_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "lag_hours": round(lag_hours, 2),
                    "limit_hours": limit_h,
                }
            )
            record_log(
                rule="STALE_STATION",
                station_id=st_id,
                rows_affected=int(len(group)),
                decision="WARN_STALE",
                reason=f"Station lag {lag_hours:.2f}h exceeds limit {limit_h}h.",
            )

    # 7. Overall Status Assessment (Probe 17 & Chapter 6 Staleness Policy)
    status_reasons: List[str] = []
    level = "OK"

    # Escalation: Unit failure / massive impossible values (Probe 17)
    if initial_valid_pm25_count > 0:
        bad_ratio = impossible_pm25_count / initial_valid_pm25_count
        if bad_ratio > config.impossible_pm25_fail_ratio:
            level = "FAIL"
            status_reasons.append(
                f"Severe unit/data error: {bad_ratio:.1%} of PM2.5 readings outside bounds."
            )

    if stale_entities:
        if level != "FAIL":
            level = "WARN_STALE"
        status_reasons.append(f"{len(stale_entities)} stations/sources are stale.")

    n_flagged = int((work["dq_flags"] != "").sum())
    if level not in ("FAIL", "WARN_STALE") and (n_flagged > 0 or len(log_entries) > 0):
        level = "WARN"

    status_dict = {
        "evaluated_at_utc": now_utc_str,
        "level": level,
        "reasons": status_reasons,
        "total_rows": int(len(work)),
        "valid_unimputed_rows": int(work["valid_obs"].sum()),
        "imputed_rows": int(work["is_imputed"].sum()),
        "missing_rows": int(work["pm25_dq"].isna().sum()),
        "flagged_rows": n_flagged,
        "stale_entities": stale_entities,
        "stale_sources": stale_entities,
        "stations_evaluated": int(work["station_id"].nunique()),
    }

    # Append to log
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_df = pd.DataFrame(
        log_entries,
        columns=["logged_at_utc", "rule", "station_id", "rows_affected", "decision", "reason"],
    )
    if not log_df.empty:
        write_header = not log_file.exists()
        log_df.to_csv(log_file, mode="a", header=write_header, index=False)
    elif not log_file.exists():
        log_df.to_csv(log_file, mode="w", header=True, index=False)

    _atomic_write_json(status_dict, Path(status_path))
    return work, status_dict


def build_processed_daily_table(
    dq_df: pd.DataFrame,
    weather_daily_df: Optional[pd.DataFrame] = None,
    min_valid_hours: int = 18,
    reference_now_utc: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    Builds daily processed table.
    Fixes P7: Drops today's ongoing, incomplete PKT calendar day!
    Training and target labels must come only from fully concluded days.
    """
    df = dq_df.copy()
    now_utc = reference_now_utc or datetime.now(timezone.utc)
    current_pkt_date = now_utc.astimezone(timezone(timedelta(hours=5))).strftime("%Y-%m-%d")

    df["date_pkt"] = df["ts_utc"].dt.tz_convert("Asia/Karachi").dt.strftime("%Y-%m-%d")

    # Exclude current incomplete PKT day (Fixes Finding P7)
    df = df[df["date_pkt"] < current_pkt_date].copy()
    if df.empty:
        return pd.DataFrame(
            columns=["row_id", "station_id", "date_pkt", "pm25_mean", "n_valid_hours", "target_next_day_pm25"]
        )

    valid_only = df.loc[df["valid_obs"]].copy()
    daily_stats = (
        valid_only.groupby(["station_id", "date_pkt"], as_index=False)
        .agg(
            pm25_mean=("pm25_dq", "mean"),
            n_valid_hours=("pm25_dq", "count"),
        )
    )

    daily_valid = daily_stats.loc[daily_stats["n_valid_hours"] >= min_valid_hours].copy()
    daily_valid = daily_valid.sort_values(["station_id", "date_pkt"]).reset_index(drop=True)

    if daily_valid.empty:
        return pd.DataFrame(
            columns=["row_id", "station_id", "date_pkt", "pm25_mean", "n_valid_hours", "target_next_day_pm25"]
        )

    daily_valid["row_id"] = daily_valid["station_id"] + "_" + daily_valid["date_pkt"]

    dt_series = pd.to_datetime(daily_valid["date_pkt"])
    next_dt = dt_series.groupby(daily_valid["station_id"]).shift(-1)
    next_pm25 = daily_valid.groupby("station_id")["pm25_mean"].shift(-1)

    is_consecutive_day = (next_dt - dt_series) == pd.Timedelta(days=1)
    daily_valid["target_next_day_pm25"] = np.where(is_consecutive_day, next_pm25, np.nan)

    if weather_daily_df is not None and not weather_daily_df.empty:
        daily_valid = daily_valid.merge(weather_daily_df, on="date_pkt", how="left")

    ProcessedDailySchema.validate(daily_valid)
    return daily_valid
