"""
export_prefect_runs.py - Check and export flow runs stored by Prefect itself.
"""
import sqlite3
from pathlib import Path


def main():
    db_path = Path.home() / ".prefect" / "prefect.db"
    if not db_path.exists():
        print(f"Prefect database not found at {db_path}.")
        print("Prefect has no history stored.")
        return

    try:
        # Open in read-only mode to prevent database locking with running scheduler
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM flow_run")
        total_runs = cur.fetchone()[0]

        cur.execute("SELECT id, name, state_name, start_time, created FROM flow_run")
        rows = cur.fetchall()
        in_range = 0
        for r in rows:
            st = str(r[3] or r[4] or "")
            if ("2026-10-20 11:00" <= st <= "2026-10-21 11:00") or ("2026-10-20T11:00" <= st <= "2026-10-21T11:00"):
                in_range += 1

        print(f"Total runs stored by Prefect itself: {total_runs}")
        print(f"Runs in range 2026-10-20 11:00Z to 2026-10-21 11:00Z: {in_range}")
        if total_runs == 0:
            print("Prefect has no history stored in its database.")
        conn.close()
    except Exception as e:
        print(f"Error inspecting Prefect database: {e}")


if __name__ == "__main__":
    main()
