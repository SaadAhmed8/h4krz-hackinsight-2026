"""
DuckDB Data Warehouse Builder (HackInsight 2026 - Chapter 5).
Persists gold processed layer tables and metadata directly into data/warehouse.duckdb.
"""
import logging
from pathlib import Path
import duckdb
import pandas as pd

logger = logging.getLogger("warehouse")

REPO_ROOT = Path(".")
DATA_DIR = REPO_ROOT / "data"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"


def build_duckdb_warehouse(db_path: Path = WAREHOUSE_PATH) -> Path:
    """
    Construct or refresh DuckDB warehouse from processed parquet tables and audit logs.
    Bulletproof against CSV sniffing failures: uses pandas DataFrames with bad line skipping
    and isolated try/except fallbacks so the hourly pipeline can NEVER crash on warehouse sync.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        con = duckdb.connect(str(db_path))
    except Exception as lock_err:
        logger.warning(f"Could not connect to DuckDB at {db_path} (file may be locked): {lock_err}")
        return db_path

    tables_created = []

    # 1. Hourly Gold Table (hourly_all)
    hourly_path = DATA_DIR / "processed" / "hourly_all.parquet"
    if hourly_path.exists():
        try:
            con.execute(f"CREATE OR REPLACE TABLE hourly_all AS SELECT * FROM read_parquet('{hourly_path.as_posix()}');")
            count = con.execute("SELECT count(*) FROM hourly_all;").fetchone()[0]
            tables_created.append(("hourly_all", count))
        except Exception as e:
            logger.warning(f"DuckDB hourly_all sync error: {e}")

    # 2. Daily Mart Table (daily)
    daily_path = DATA_DIR / "processed" / "daily.parquet"
    if daily_path.exists():
        try:
            con.execute(f"CREATE OR REPLACE TABLE daily_mart AS SELECT * FROM read_parquet('{daily_path.as_posix()}');")
            count = con.execute("SELECT count(*) FROM daily_mart;").fetchone()[0]
            tables_created.append(("daily_mart", count))
        except Exception as e:
            logger.warning(f"DuckDB daily_mart sync error: {e}")

    # 3. Daily Station Table (daily_station_table)
    daily_st_path = DATA_DIR / "processed" / "daily_station_table.parquet"
    if daily_st_path.exists():
        try:
            con.execute(f"CREATE OR REPLACE TABLE daily_station_table AS SELECT * FROM read_parquet('{daily_st_path.as_posix()}');")
            count = con.execute("SELECT count(*) FROM daily_station_table;").fetchone()[0]
            tables_created.append(("daily_station_table", count))
        except Exception as e:
            logger.warning(f"DuckDB daily_station_table sync error: {e}")

    # 4. Cleaned Weather (weather_cleaned)
    weather_clean_path = DATA_DIR / "cleaned" / "weather_cleaned.parquet"
    if weather_clean_path.exists():
        try:
            con.execute(f"CREATE OR REPLACE TABLE weather_cleaned AS SELECT * FROM read_parquet('{weather_clean_path.as_posix()}');")
            count = con.execute("SELECT count(*) FROM weather_cleaned;").fetchone()[0]
            tables_created.append(("weather_cleaned", count))
        except Exception as e:
            logger.warning(f"DuckDB weather_cleaned sync error: {e}")

    # 5. Daily Weather (weather_daily)
    weather_daily_path = DATA_DIR / "cleaned" / "weather_daily.parquet"
    if weather_daily_path.exists():
        try:
            con.execute(f"CREATE OR REPLACE TABLE weather_daily AS SELECT * FROM read_parquet('{weather_daily_path.as_posix()}');")
            count = con.execute("SELECT count(*) FROM weather_daily;").fetchone()[0]
            tables_created.append(("weather_daily", count))
        except Exception as e:
            logger.warning(f"DuckDB weather_daily sync error: {e}")

    # 6. Quality Decisions Log (quality_log) - Bulletproof via pandas DataFrame
    qlog_path = DATA_DIR / "cleaned" / "quality_log.csv"
    if qlog_path.exists():
        try:
            q_df = pd.read_csv(qlog_path, on_bad_lines="skip", dtype=str)
            con.register("q_df_view", q_df)
            con.execute("CREATE OR REPLACE TABLE quality_log AS SELECT * FROM q_df_view;")
            con.unregister("q_df_view")
            count = con.execute("SELECT count(*) FROM quality_log;").fetchone()[0]
            tables_created.append(("quality_log", count))
        except Exception as q_err:
            logger.warning(f"DuckDB quality_log fallback: {q_err}")

    # 7. Audit Manifest (manifest) - Bulletproof via pandas DataFrame
    manifest_path = REPO_ROOT / "manifest.csv"
    if manifest_path.exists():
        try:
            m_df = pd.read_csv(manifest_path, on_bad_lines="skip", dtype=str)
            con.register("m_df_view", m_df)
            con.execute("CREATE OR REPLACE TABLE manifest AS SELECT * FROM m_df_view;")
            con.unregister("m_df_view")
            count = con.execute("SELECT count(*) FROM manifest;").fetchone()[0]
            tables_created.append(("manifest", count))
        except Exception as m_err:
            logger.warning(f"DuckDB manifest fallback: {m_err}")

    con.close()

    logger.info(f"DuckDB warehouse built successfully at {db_path} with tables:")
    for t_name, cnt in tables_created:
        logger.info(f"  - {t_name}: {cnt:,} rows")

    return db_path


def main():
    build_duckdb_warehouse()


if __name__ == "__main__":
    main()
