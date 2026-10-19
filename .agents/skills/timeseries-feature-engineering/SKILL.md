---
name: timeseries-feature-engineering
description: "Guidelines and rules for air quality time-series feature engineering. Covers PKT calendar alignment, the 18/24-hour validity rule on non-imputed readings, zero-leakage lag and rolling features, and beating naive baselines."
---

# Timeseries Feature Engineering Skill — HackInsight 2026

Patterns and guardrails for tabular/time-series ML modeling on Lahore PM2.5 data. Designed to construct leakage-free predictive features that beat the naive persistence baseline by $\ge 15\%$ MAE.

## 1. Calendar Day Alignment (PKT / Asia/Karachi)

Raw data is stored in UTC (`ts_utc`). Daily aggregations **must** be framed strictly under Pakistan Standard Time (`Asia/Karachi`, UTC+5) so that midnight-to-midnight captures local human activity cycles (smog, traffic, agricultural burns).

```python
# Correct calendar day extraction
df["date_pkt"] = df["ts_utc"].dt.tz_convert("Asia/Karachi").dt.strftime("%Y-%m-%d")
```

## 2. The $\ge 18/24$ Valid Hour Rule (Strict Non-Imputed)

To avoid training models on synthetic or unrepresentative days:
- Calculate daily mean **only** on hours where `valid_obs == True`.
- `valid_obs` is defined as: `pm25_dq.notna() & (~is_imputed)`.
- If a station has $< 18$ valid, non-imputed hours in a PKT calendar day, **drop the station-day entirely**.

```python
valid_only = df.loc[df["valid_obs"]].copy()
daily_stats = valid_only.groupby(["station_id", "date_pkt"], as_index=False).agg(
    pm25_mean=("pm25_dq", "mean"),
    n_valid_hours=("pm25_dq", "count"),
)

daily_valid = daily_stats.loc[daily_stats["n_valid_hours"] >= 18].copy()
```

## 3. Strict Consecutive-Day Target Generation

The competition prediction target is tomorrow's 24-hour mean PM2.5 (`target_next_day_pm25`). If a station is missing data for day $T+1$, day $T$ must **not** shift values from $T+2$:

```python
dt_series = pd.to_datetime(daily_valid["date_pkt"])
next_dt = dt_series.groupby(daily_valid["station_id"]).shift(-1)
next_pm25 = daily_valid.groupby("station_id")["pm25_mean"].shift(-1)

is_consecutive_day = (next_dt - dt_series) == pd.Timedelta(days=1)
daily_valid["target_next_day_pm25"] = np.where(is_consecutive_day, next_pm25, np.nan)
```

## 4. Zero Data Leakage Feature Engineering

All features for predicting day $T+1$ must only use information available up through day $T$.

### Feature Suite
1. **Lags:**
   - `pm25_lag_1d`: Day $T$ mean ($s(t)$)
   - `pm25_lag_2d`: Day $T-1$ mean ($s(t-1)$)
   - `pm25_lag_3d`: Day $T-2$ mean ($s(t-2)$)
2. **Rolling Statistics (Closed='left' or explicit shifts):**
   - `pm25_rolling_mean_3d`: 3-day trailing average
   - `pm25_rolling_std_3d`: Volatility / stability indicator
   - `pm25_momentum_1d`: `pm25_lag_1d - pm25_lag_2d`
3. **Temporal Features:**
   - Day of week (0-6)
   - Month / Day of year (seasonal smog indicators)
4. **Exogenous Weather Features:**
   - Join daily aggregates (`temp_c_mean`, `rh_mean`, `wind_speed_mean`) from OpenMeteo for day $T$.

```python
# Per station group to prevent cross-station bleeding
def build_station_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["station_id", "date_pkt"]).copy()
    g = df.groupby("station_id")["pm25_mean"]

    df["pm25_lag_1d"] = g.shift(0)  # On day T, lag 1 for tomorrow is today's reading
    df["pm25_lag_2d"] = g.shift(1)
    df["pm25_lag_3d"] = g.shift(2)

    df["pm25_rolling_mean_3d"] = g.transform(lambda s: s.shift(0).rolling(3, min_periods=2).mean())
    df["pm25_momentum_1d"] = df["pm25_lag_1d"] - df["pm25_lag_2d"]
    return df
```

## 5. Validation Strategy & Benchmark Baseline

- **Time-based Split Only:** Never use random K-Fold cross validation on timeseries data. Use temporal train/test cutoffs (e.g., Train on earlier dates, evaluate on the most recent 14-30 days).
- **Target Performance Metric:** Mean Absolute Error (MAE).
- **Naive Baseline Rule:** Persistence baseline $\hat{y}_{t+1} = y_t$ (`MAE_naive = mean(|pm25_mean - target_next_day_pm25|)`).
- **Goal:** Model MAE must beat `MAE_naive` by at least $15\%$ (`MAE_model <= 0.85 * MAE_naive`).
