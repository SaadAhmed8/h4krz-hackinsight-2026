"""
scripts/export_prefect_runs.py
Official Prefect run-history export script for HackInsight 2026 (Team H4krz).

IMPORTANT EXECUTION NOTICE (Guide Chapter 10):
This script MUST be run AFTER Wednesday 21 October 2026, 4:00 PM PKT (11:00:00 UTC)
on the machine whose Prefect server/profile ran the hourly flow.

It queries the Prefect client via read_flow_runs across the 24-hour evaluation window:
  Window Start: 2026-10-20T11:00:00Z (Tuesday 4:00 PM PKT)
  Window End:   2026-10-21T11:00:00Z (Wednesday 4:00 PM PKT)

Exports unedited flow runs to ./prefect_runs.csv with columns:
  flow_run_id, flow_name, flow_run_name, state_type, state_name,
  expected_start_time_utc, start_time_utc, end_time_utc,
  total_run_time_seconds, deployment_id

Integrity Guarantees:
- No filtering of failures; all states (COMPLETED, FAILED, CRASHED, etc.) are exported.
- No synthetic or invented rows.
- Prints exact counts per state.
"""
import sys
import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
import pandas as pd

from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterStartTime

WINDOW_START = datetime(2026, 10, 20, 11, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 10, 21, 11, 0, 0, tzinfo=timezone.utc)
DEFAULT_OUTPUT = Path("prefect_runs.csv")


def _ensure_prefect_server_url():
    """Ensure local server connection if running against local port 4200."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        res = s.connect_ex(("127.0.0.1", 4200))
        s.close()
        if res == 0:
            os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")
    except Exception:
        pass


async def fetch_prefect_runs(window_start: datetime, window_end: datetime):
    _ensure_prefect_server_url()
    async with get_client() as client:
        flow_filter = FlowRunFilter(
            start_time=FlowRunFilterStartTime(
                after_=window_start,
                before_=window_end,
            )
        )
        
        # Paginate flow runs in chunks of 200 (Prefect API maximum limit per request is 200)
        runs = []
        offset = 0
        limit = 200
        while True:
            chunk = await client.read_flow_runs(
                flow_run_filter=flow_filter,
                limit=limit,
                offset=offset,
            )
            if not chunk:
                break
            runs.extend(chunk)
            if len(chunk) < limit:
                break
            offset += limit

        flows_cache = {}
        records = []
        for r in runs:
            # Resolve flow name from flow_id
            flow_name = "unknown"
            if r.flow_id:
                if r.flow_id in flows_cache:
                    flow_name = flows_cache[r.flow_id]
                else:
                    try:
                        flow_obj = await client.read_flow(r.flow_id)
                        flow_name = flow_obj.name
                        flows_cache[r.flow_id] = flow_name
                    except Exception:
                        flow_name = str(r.flow_id)

            # Format timestamps
            exp_start = r.expected_start_time.isoformat() if r.expected_start_time else ""
            start_t = r.start_time.isoformat() if r.start_time else ""
            end_t = r.end_time.isoformat() if r.end_time else ""

            # Format total run time in seconds
            tot_sec = 0.0
            if r.total_run_time is not None:
                if hasattr(r.total_run_time, "total_seconds"):
                    tot_sec = r.total_run_time.total_seconds()
                else:
                    try:
                        tot_sec = float(r.total_run_time)
                    except (ValueError, TypeError):
                        tot_sec = 0.0

            # State type representation
            st_type = r.state_type.value if hasattr(r.state_type, "value") else str(r.state_type)
            st_name = r.state_name if r.state_name else st_type

            records.append({
                "flow_run_id": str(r.id),
                "flow_name": flow_name,
                "flow_run_name": r.name,
                "state_type": st_type,
                "state_name": st_name,
                "expected_start_time_utc": exp_start,
                "start_time_utc": start_t,
                "end_time_utc": end_t,
                "total_run_time_seconds": round(tot_sec, 2),
                "deployment_id": str(r.deployment_id) if r.deployment_id else "",
            })

        return records


def export_runs(output_path: Path = DEFAULT_OUTPUT, dry_run: bool = False):
    now_utc = datetime.now(timezone.utc)
    print("=" * 65)
    print(" HackInsight 2026: Official Prefect Run-History Export")
    print("=" * 65)
    print(f"Current UTC Time: {now_utc.isoformat()}")
    print(f"Target Window:    {WINDOW_START.isoformat()} to {WINDOW_END.isoformat()}")
    print(f"Target Window PKT: Tue 20 Oct 4:00 PM to Wed 21 Oct 4:00 PM PKT")

    if now_utc < WINDOW_END and not dry_run:
        print("\n[WARNING] Current time is BEFORE the end of the 24-hour evaluation window!")
        print("Per Guide Chapter 10, the official final export must be run AFTER Wed 4:00 PM PKT.")

    try:
        records = asyncio.run(fetch_prefect_runs(WINDOW_START, WINDOW_END))
    except Exception as e:
        print(f"\n[ERROR] Could not connect to Prefect API or query flow runs: {e}")
        print("Ensure your Prefect server is running (e.g. 'prefect server start') and PREFECT_API_URL is configured.")
        return 1

    print(f"\nTotal flow runs queried in window: {len(records)}")

    # Print counts per state
    state_counts = Counter(r["state_name"] for r in records)
    print("\n--- Runs Per State ---")
    if state_counts:
        for state, count in sorted(state_counts.items()):
            print(f"  {state}: {count}")
    else:
        print("  (No runs found in specified window)")

    state_type_counts = Counter(r["state_type"] for r in records)
    print("\n--- Runs Per State Type ---")
    for st_type, count in sorted(state_type_counts.items()):
        print(f"  {st_type}: {count}")

    if dry_run:
        print("\n[DRY RUN] Finished without writing output file.")
        return 0

    # Write out strictly to output_path
    df = pd.DataFrame(records, columns=[
        "flow_run_id",
        "flow_name",
        "flow_run_name",
        "state_type",
        "state_name",
        "expected_start_time_utc",
        "start_time_utc",
        "end_time_utc",
        "total_run_time_seconds",
        "deployment_id"
    ])
    # Sort chronologically by start_time_utc
    df = df.sort_values("start_time_utc", ascending=True)
    df.to_csv(output_path, index=False)
    print(f"\nSuccessfully wrote {len(df)} unedited run records to '{output_path}'.")
    return 0


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    out_file = DEFAULT_OUTPUT
    for arg in sys.argv[1:]:
        if arg.startswith("--output="):
            out_file = Path(arg.split("=", 1)[1])
        elif arg == "--output" and sys.argv.index(arg) + 1 < len(sys.argv):
            out_file = Path(sys.argv[sys.argv.index(arg) + 1])

    code = export_runs(output_path=out_file, dry_run=is_dry)
    sys.exit(code)
