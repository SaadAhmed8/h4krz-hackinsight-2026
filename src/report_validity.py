"""
Reproducible Validity and True Hourly Readings Reporter.
Computes and reports:
- Calendar hours vs Real non-missing PM2.5 readings
- Non-missing hours after quality flagging
- Longest missing gap in hours
- Valid PKT days (>= 18 valid hours) and invalid days
- Total PM2.5 real readings across stations vs the 50,000 requirement
- Monthly breakdown of valid days
- Verification that daily.parquet n_valid_pm25_hours and is_valid_day match independent recomputation
Saves summary to reports/station_validity.csv and reports/monthly_validity.csv.

Guards:
- Exits non-zero with a clear message if:
  * total PKT days == 0
  * any station slug is not found in config/stations.yaml
  * zero station-days were compared in the agreement check
- Sets pandas display options so tables do not wrap.
"""
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd
import numpy as np
import yaml

logger = logging.getLogger("report_validity")

CLEANED_DIR = Path("data/cleaned")
PROCESSED_DIR = Path("data/processed")
CONFIG_PATH = Path("config/stations.yaml")
REPORTS_DIR = Path("reports")
HOURLY_FILE = PROCESSED_DIR / "hourly_all.parquet"
DAILY_FILE = PROCESSED_DIR / "daily.parquet"
CSV_OUT = REPORTS_DIR / "station_validity.csv"
MONTHLY_CSV_OUT = REPORTS_DIR / "monthly_validity.csv"

# Configure pandas display options to prevent table wrapping
pd.set_option("display.max_columns", None)
pd.set_option("display.max_rows", None)
pd.set_option("display.width", 1000)
pd.set_option("display.colheader_justify", "left")


def load_configured_station_slugs(config_path: Path = CONFIG_PATH) -> List[str]:
    """Load valid station slugs from stations.yaml config."""
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [s.get("slug") for s in data.get("stations", []) if s.get("slug")]


def compute_longest_gap(series_notna: pd.Series) -> int:
    """Compute maximum consecutive missing (False) hours in a boolean series."""
    if series_notna.all():
        return 0
    if not series_notna.any():
        return len(series_notna)

    is_missing = ~series_notna
    run_id = (is_missing != is_missing.shift(1)).cumsum()
    missing_runs = run_id[is_missing]
    if missing_runs.empty:
        return 0
    return int(missing_runs.value_counts().max())


def generate_validity_report() -> Dict[str, Any]:
    """Generate station validity analysis from data/cleaned and data/processed."""
    if not HOURLY_FILE.exists() or not DAILY_FILE.exists():
        raise FileNotFoundError(f"Processed files not found at {HOURLY_FILE} or {DAILY_FILE}. Run pipeline first.")

    configured_slugs = set(load_configured_station_slugs())

    hourly_df = pd.read_parquet(HOURLY_FILE)
    daily_df = pd.read_parquet(DAILY_FILE)

    # GUARD 1: Verify total PKT days > 0
    total_pkt_days_in_daily = len(daily_df)
    if total_pkt_days_in_daily == 0:
        logger.error("VALIDITY CHECK FAILED: total PKT days == 0 in daily.parquet!")
        sys.exit(1)

    # GUARD 2: Verify all station slugs belong to station config
    hourly_slugs = set(hourly_df["station_slug"].unique())
    daily_slugs = set(daily_df["station_slug"].unique())
    unrecognized_slugs = (hourly_slugs | daily_slugs) - configured_slugs

    if unrecognized_slugs:
        logger.error(
            f"VALIDITY CHECK FAILED: Unrecognized station slug(s) found in data that are not in {CONFIG_PATH}: {unrecognized_slugs}"
        )
        sys.exit(1)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    station_summaries = []
    total_compared_station_days = 0
    total_agreement_mismatches = 0

    print("\n" + "=" * 135)
    print("                    STATION-LEVEL AIR QUALITY VALIDITY & COVERAGE AUDIT")
    print("=" * 135)

    for slug, grp in hourly_df.groupby("station_slug"):
        grp = grp.sort_values("timestamp_utc").reset_index(drop=True)
        st_name = grp["station_name"].iloc[0] if "station_name" in grp else slug
        first_ts = grp["timestamp_utc"].min()
        last_ts = grp["timestamp_utc"].max()
        calendar_hours = len(grp)

        # Real raw PM2.5 readings present
        real_pm25_hours = int(grp["pm25"].notna().sum())

        # Non-missing after removing flagged rows
        if "is_flagged" in grp.columns:
            unflagged_hours = int((grp["pm25"].notna() & (~grp["is_flagged"])).sum())
            flagged_hours = real_pm25_hours - unflagged_hours
        else:
            unflagged_hours = real_pm25_hours
            flagged_hours = 0

        pct_missing = ((calendar_hours - real_pm25_hours) / calendar_hours) * 100.0 if calendar_hours > 0 else 0.0
        longest_gap_hrs = compute_longest_gap(grp["pm25"].notna())

        # Daily mart re-computation and agreement check
        d_grp = daily_df[daily_df["station_slug"] == slug]
        total_pkt_days = len(d_grp)
        valid_pkt_days = int(d_grp["is_valid_day"].sum())
        invalid_pkt_days = total_pkt_days - valid_pkt_days
        valid_day_pct = (valid_pkt_days / total_pkt_days * 100.0) if total_pkt_days > 0 else 0.0

        # Independent recomputation of valid hours per day to check agreement
        day_mismatches = 0
        for pkt_d, d_hours in grp.groupby("pkt_date"):
            recomputed_valid_hours = int((d_hours["pm25"].notna() & (~d_hours.get("is_flagged", False))).sum())
            recomputed_is_valid = (recomputed_valid_hours >= 18)
            
            # Lookup in daily_df
            match_row = d_grp[d_grp["pkt_date"] == str(pkt_d)]
            if not match_row.empty:
                total_compared_station_days += 1
                recorded_valid_hours = match_row.iloc[0]["n_valid_pm25_hours"]
                recorded_is_valid = match_row.iloc[0]["is_valid_day"]
                if recorded_valid_hours != recomputed_valid_hours or recorded_is_valid != recomputed_is_valid:
                    day_mismatches += 1
                    total_agreement_mismatches += 1

        station_summaries.append({
            "station_slug": slug,
            "station_name": st_name,
            "first_timestamp_utc": str(first_ts),
            "last_timestamp_utc": str(last_ts),
            "calendar_hours": calendar_hours,
            "real_pm25_hours": real_pm25_hours,
            "flagged_hours": flagged_hours,
            "unflagged_valid_hours": unflagged_hours,
            "pct_missing": round(pct_missing, 2),
            "longest_gap_hours": longest_gap_hrs,
            "total_pkt_days": total_pkt_days,
            "valid_pkt_days": valid_pkt_days,
            "invalid_pkt_days": invalid_pkt_days,
            "valid_day_pct": round(valid_day_pct, 2),
            "agreement_mismatches": day_mismatches
        })

    # GUARD 3: Verify zero station-days were NOT compared
    if total_compared_station_days == 0:
        logger.error("VALIDITY CHECK FAILED: Zero station-days were compared in the agreement check!")
        sys.exit(1)

    summary_df = pd.DataFrame(station_summaries)
    summary_df.to_csv(CSV_OUT, index=False)

    # Print clean unwrapped summary table
    print(summary_df[[
        "station_slug", "calendar_hours", "real_pm25_hours", "unflagged_valid_hours",
        "pct_missing", "longest_gap_hours", "valid_pkt_days", "invalid_pkt_days", "valid_day_pct"
    ]].to_string(index=False))

    total_real_pm25 = summary_df["real_pm25_hours"].sum()
    total_unflagged_pm25 = summary_df["unflagged_valid_hours"].sum()
    total_calendar_hours = summary_df["calendar_hours"].sum()
    total_valid_days = summary_df["valid_pkt_days"].sum()
    total_days = summary_df["total_pkt_days"].sum()

    print("\n" + "=" * 135)
    print("                              WAREHOUSE TOTALS & BENCHMARK AUDIT")
    print("=" * 135)
    print(f"Total Calendar Grid Hours:         {total_calendar_hours:,}")
    print(f"Total Real PM2.5 Readings:         {total_real_pm25:,}")
    print(f"Total Clean Unflagged Readings:    {total_unflagged_pm25:,}")
    print(f"50,000-Row Requirement Target:     50,000 readings")
    print(f"Target Requirement Margin:         +{total_real_pm25 - 50000:,} readings ({total_real_pm25/50000*100:.1f}% of goal)")
    print(f"Total PKT Days:                    {total_days:,}")
    print(f"Total Valid PKT Days (>=18h):      {total_valid_days:,} ({total_valid_days/total_days*100:.1f}%)")
    print(f"Station-Days Verified in Audit:    {total_compared_station_days:,} days compared")
    
    if total_agreement_mismatches == 0 and total_compared_station_days > 0:
        print(f"Daily Mart Agreement Status:       PERFECT ({total_compared_station_days:,}/{total_compared_station_days:,} matched, 0 mismatches)")
    else:
        print(f"Daily Mart Agreement Status:       DISCREPANCY ({total_agreement_mismatches} mismatches detected!)")
    print("=" * 135)

    # Monthly Breakdown
    print("\n" + "=" * 135)
    print("                           MONTHLY VALID-DAY BREAKDOWN PER STATION")
    print("=" * 135)
    daily_df["month_str"] = pd.to_datetime(daily_df["pkt_date"]).dt.to_period("M").astype(str)

    valid_pivot = daily_df.pivot_table(
        index="station_slug",
        columns="month_str",
        values="is_valid_day",
        aggfunc="sum",
        fill_value=0
    )
    total_month_pivot = daily_df.pivot_table(
        index="station_slug",
        columns="month_str",
        values="is_valid_day",
        aggfunc="count",
        fill_value=0
    )
    
    monthly_str_df = pd.DataFrame(index=valid_pivot.index)
    for col in valid_pivot.columns:
        monthly_str_df[col] = valid_pivot[col].astype(str) + "/" + total_month_pivot[col].astype(str)

    print(monthly_str_df.to_string())
    monthly_str_df.to_csv(MONTHLY_CSV_OUT)
    print(f"\nWrote station validity to {CSV_OUT}")
    print(f"Wrote monthly breakdown to {MONTHLY_CSV_OUT}\n")

    return {
        "summary": summary_df,
        "total_real_pm25": total_real_pm25,
        "is_above_50k": (total_real_pm25 >= 50000),
        "total_compared_station_days": total_compared_station_days,
        "total_agreement_mismatches": total_agreement_mismatches,
        "monthly_breakdown": monthly_str_df
    }


def main():
    try:
        generate_validity_report()
    except Exception as e:
        logger.error(f"Validity report generation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
