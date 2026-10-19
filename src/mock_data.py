# src/mock_data.py
"""Deterministic synthetic station batch for local dry-runs (mirrors tests/test_dq_agent.py fixture)."""
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

MOCK_STATIONS = [
    "lahore_model_town", "lahore_gulberg", "lahore_johar_town", "lahore_dha",
    "lahore_shadman", "lahore_township", "lahore_cantt", "hawanama_iqbal_town",
    "hawanama_wapda_town", "hawanama_shahdara",
]


def make_mock_batch(
    hours: int = 48,
    end_utc: Optional[datetime] = None,
    n_stations: int = 10,
) -> pd.DataFrame:
    """
    Same sinusoidal pattern as the test fixture `_make_base_df`, per station with a fixed offset.
    Ends at the current UTC hour so the stale-source rule stays green.
    48h by default so at least one full PKT calendar day passes the 18/24 rule.
    Hawanama stations omit rh/temp_c (NaN) to exercise the optional-column path.
    """
    end = pd.Timestamp(end_utc or datetime.now(timezone.utc)).floor("h")
    ts = pd.date_range(end=end, periods=hours, freq="1h")
    frames = []
    for i, st in enumerate(MOCK_STATIONS[:n_stations]):
        k = np.arange(hours)
        is_hawanama = st.startswith("hawanama")
        frames.append(
            pd.DataFrame(
                {
                    "station_id": st,
                    "ts_utc": ts,
                    "pm25": 50.0 + 5.0 * i + 10.0 * np.sin(k + i),
                    "source": "openaq",
                    "fetched_at_utc": ts + pd.Timedelta(minutes=5),
                    "rh": np.nan if is_hawanama else 55.0 + 10.0 * np.cos(k / 4.0),
                    "temp_c": np.nan if is_hawanama else 22.0 + 6.0 * np.sin(k / 4.0),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
