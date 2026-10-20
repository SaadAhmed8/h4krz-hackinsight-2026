"""
DuckDB Data Warehouse Builder (HackInsight 2026 - Chapter 5).
Persists gold processed layer tables and metadata directly into data/warehouse.duckdb.
"""
import logging
from pathlib import Path
import duckdb

logger = logging.getLogger("warehouse")

REPO_ROOT = Path(".")
DATA_DIR = REPO_ROOT / "data"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"


def build_duckdb_warehouse(db_path: Path = WAREHOUSE_PATH) -> Path:
    """
    Construct or refresh DuckDB warehouse from processed parquet tables and audit logs.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))

    tables_created = []

    # 1. Hourly Gold Table (hourly_all)
    hourly_path = DATA_DIR / "processed" / "hourly_all.parquet"
    if hourly_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE hourly_all AS SELECT * FROM read_parquet('{hourly_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM hourly_all;").fetchone()[0]
        tables_created.append(("hourly_all", count))

    # 2. Daily Mart Table (daily)
    daily_path = DATA_DIR / "processed" / "daily.parquet"
    if daily_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE daily_mart AS SELECT * FROM read_parquet('{daily_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM daily_mart;").fetchone()[0]
        tables_created.append(("daily_mart", count))

    # 3. Daily Station Table (daily_station_table)
    daily_st_path = DATA_DIR / "processed" / "daily_station_table.parquet"
    if daily_st_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE daily_station_table AS SELECT * FROM read_parquet('{daily_st_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM daily_station_table;").fetchone()[0]
        tables_created.append(("daily_station_table", count))

    # 4. Cleaned Weather (weather_cleaned)
    weather_clean_path = DATA_DIR / "cleaned" / "weather_cleaned.parquet"
    if weather_clean_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE weather_cleaned AS SELECT * FROM read_parquet('{weather_clean_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM weather_cleaned;").fetchone()[0]
        tables_created.append(("weather_cleaned", count))

    # 5. Daily Weather (weather_daily)
    weather_daily_path = DATA_DIR / "cleaned" / "weather_daily.parquet"
    if weather_daily_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE weather_daily AS SELECT * FROM read_parquet('{weather_daily_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM weather_daily;").fetchone()[0]
        tables_created.append(("weather_daily", count))

    # 6. Quality Decisions Log (quality_log)
    qlog_path = DATA_DIR / "cleaned" / "quality_log.csv"
    if qlog_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE quality_log AS SELECT * FROM read_csv_auto('{qlog_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM quality_log;").fetchone()[0]
        tables_created.append(("quality_log", count))

    # 7. Audit Manifest (manifest)
    manifest_path = REPO_ROOT / "manifest.csv"
    if manifest_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE manifest AS SELECT * FROM read_csv_auto('{manifest_path.as_posix()}');")
        count = con.execute("SELECT count(*) FROM manifest;").fetchone()[0]
        tables_created.append(("manifest", count))

    con.close()

    logger.info(f"DuckDB warehouse built successfully at {db_path} with tables:")
    for t_name, cnt in tables_created:
        logger.info(f"  - {t_name}: {cnt:,} rows")

    return db_path


def main():
    build_duckdb_warehouse()


if __name__ == "__main__":
    main()
