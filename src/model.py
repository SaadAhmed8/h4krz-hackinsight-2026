"""
Model, Uncertainty & Group Fairness Module (Chapters 7 & 8).
Features:
- Chronological time-based split on data/processed/daily.parquet (70% train, 15% validation, 15% test).
- Preprocessing imputers/scalers fit strictly on train set only (prevent data leakage).
- Baseline persistence model comparison: pred = today's mean (pm25_daily_mean).
- Reports MAE improvement over the persistence baseline on the chronological test split (no next-day weather features).
- Uncertainty intervals via quantile HistGradientBoostingRegressor (10th and 90th percentiles).
- Slice-based group fairness error breakdown saved to reports/model_errors_by_group.csv.
- Experimental optimization log saved to reports/optimization_log.csv.
- Full prediction outputs saved to data/processed/predictions.parquet and predictions.csv.
"""
import os
import sys
import time
import json
import logging
import tracemalloc
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.preprocessing import OrdinalEncoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("model")

PROCESSED_DIR = Path("data/processed")
REPORTS_DIR = Path("reports")
DAILY_PATH = PROCESSED_DIR / "daily.parquet"
PREDICTIONS_PARQUET = PROCESSED_DIR / "predictions.parquet"
PREDICTIONS_CSV = PROCESSED_DIR / "predictions.csv"
ERRORS_BY_GROUP_CSV = REPORTS_DIR / "model_errors_by_group.csv"
OPTIMIZATION_LOG_CSV = REPORTS_DIR / "optimization_log.csv"


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """Engineer robust feature set from daily dataframe."""
    work = df.copy()
    st_col = "station_slug" if "station_slug" in work.columns else "station_id"
    date_col = "pkt_date" if "pkt_date" in work.columns else "date_pkt"

    work = work.sort_values([st_col, date_col]).reset_index(drop=True)

    # Base numerical features
    num_cols = [
        "pm25_daily_mean",
        "pm25_lag_1d",
        "pm25_lag_2d",
        "pm25_lag_7d_rolling_mean",
        "weather_temp_mean_c",
        "weather_temp_max_c",
        "weather_rh_mean_pct",
        "weather_wind_mean_kmh",
        "weather_wind_max_kmh",
        "weather_precip_sum_mm",
        "calendar_month",
        "calendar_day_of_week",
    ]
    for c in num_cols:
        if c in work.columns:
            work[c] = pd.to_numeric(work[c], errors="coerce")

    # Lag differentials & acceleration
    work["pm25_diff_1d"] = work["pm25_daily_mean"] - work["pm25_lag_1d"]
    work["pm25_diff_2d"] = work["pm25_lag_1d"] - work["pm25_lag_2d"]
    work["pm25_diff_7d"] = work["pm25_daily_mean"] - work["pm25_lag_7d_rolling_mean"]
    num_cols.extend(["pm25_diff_1d", "pm25_diff_2d", "pm25_diff_7d"])

    # Spatial / cross-station signals
    work["city_mean"] = work.groupby(date_col)["pm25_daily_mean"].transform("mean")
    work["city_diff"] = work["pm25_daily_mean"] - work["city_mean"]
    work["city_mean_lag1"] = work.groupby(st_col)["city_mean"].shift(1)
    work["city_trend"] = work["city_mean"] - work["city_mean_lag1"]
    num_cols.extend(["city_mean", "city_diff", "city_trend"])

    # Cyclical calendar features
    if "calendar_month" in work.columns:
        work["month_sin"] = np.sin(2 * np.pi * work["calendar_month"] / 12.0)
        work["month_cos"] = np.cos(2 * np.pi * work["calendar_month"] / 12.0)
        num_cols.extend(["month_sin", "month_cos"])

    # Ensure all columns are numeric
    for c in num_cols:
        work[c] = pd.to_numeric(work[c], errors="coerce")

    # Filter available columns
    available_cols = [c for c in num_cols if c in work.columns]
    return work, available_cols


def chronological_split(
    df: pd.DataFrame,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Perform a strict chronological time-based split across distinct dates.
    70% train, 15% validation, 15% test.
    Prevents temporal data leakage.
    """
    date_col = "pkt_date" if "pkt_date" in df.columns else "date_pkt"
    unique_dates = sorted(df[date_col].dropna().unique())
    n_dates = len(unique_dates)

    n_train = int(n_dates * train_frac)
    n_val = int(n_dates * val_frac)

    train_dates = set(unique_dates[:n_train])
    val_dates = set(unique_dates[n_train:n_train + n_val])
    test_dates = set(unique_dates[n_train + n_val:])

    train_df = df[df[date_col].isin(train_dates)].copy().reset_index(drop=True)
    val_df = df[df[date_col].isin(val_dates)].copy().reset_index(drop=True)
    test_df = df[df[date_col].isin(test_dates)].copy().reset_index(drop=True)

    logger.info(
        f"Chronological split: {len(train_dates)} train dates ({len(train_df)} rows), "
        f"{len(val_dates)} val dates ({len(val_df)} rows), "
        f"{len(test_dates)} test dates ({len(test_df)} rows)."
    )
    return train_df, val_df, test_df


def train_and_evaluate_iteration(
    name: str,
    feature_cols: List[str],
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    target_col: str = "target_next_day_pm25",
    baseline_col: str = "pm25_daily_mean",
    predict_residual: bool = True,
    hgb_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Train single iteration model and track runtime & memory."""
    tracemalloc.start()
    start_t = time.perf_counter()

    # 1. Fit Imputer strictly on train set only
    imputer = SimpleImputer(strategy="median")
    X_train_imp = imputer.fit_transform(train_df[feature_cols])
    X_val_imp = imputer.transform(val_df[feature_cols])
    X_test_imp = imputer.transform(test_df[feature_cols])

    # Categorical station encoding fit strictly on train
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    st_col = "station_slug" if "station_slug" in train_df.columns else "station_id"
    st_train = encoder.fit_transform(train_df[[st_col]])
    st_val = encoder.transform(val_df[[st_col]])
    st_test = encoder.transform(test_df[[st_col]])

    X_train = np.hstack([X_train_imp, st_train])
    X_val = np.hstack([X_val_imp, st_val])
    X_test = np.hstack([X_test_imp, st_test])

    if predict_residual:
        y_train = train_df[target_col].values - train_df[baseline_col].values
    else:
        y_train = train_df[target_col].values

    y_val_actual = val_df[target_col].values
    y_test_actual = test_df[target_col].values

    # Train point model
    params = hgb_params or {"max_iter": 100, "random_state": 42}
    model = HistGradientBoostingRegressor(
        categorical_features=[X_train.shape[1] - 1],
        **params
    )
    model.fit(X_train, y_train)

    if predict_residual:
        val_preds = val_df[baseline_col].values + model.predict(X_val)
        test_preds = test_df[baseline_col].values + model.predict(X_test)
    else:
        val_preds = model.predict(X_val)
        test_preds = model.predict(X_test)

    val_mae = mean_absolute_error(y_val_actual, val_preds)
    test_mae = mean_absolute_error(y_test_actual, test_preds)
    baseline_test_mae = mean_absolute_error(y_test_actual, test_df[baseline_col].values)
    improvement_pct = ((baseline_test_mae - test_mae) / baseline_test_mae) * 100.0

    runtime_sec = time.perf_counter() - start_t
    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = round(peak_mem / (1024 * 1024), 2)

    return {
        "name": name,
        "model": model,
        "imputer": imputer,
        "encoder": encoder,
        "feature_cols": feature_cols,
        "predict_residual": predict_residual,
        "valid_mae": round(val_mae, 3),
        "test_mae": round(test_mae, 3),
        "baseline_test_mae": round(baseline_test_mae, 3),
        "improvement_pct": round(improvement_pct, 2),
        "runtime_seconds": round(runtime_sec, 3),
        "peak_memory_mb": peak_mem_mb,
        "val_preds": val_preds,
        "test_preds": test_preds,
    }


def train_quantile_models(
    X_train: np.ndarray,
    y_train_residual: np.ndarray,
    categorical_idx: int,
    hgb_params: Optional[Dict[str, Any]] = None,
) -> Tuple[HistGradientBoostingRegressor, HistGradientBoostingRegressor]:
    """Train 10th and 90th percentile quantile gradient boosting models for uncertainty intervals."""
    params = dict(hgb_params or {})
    params.pop("loss", None)

    lower_model = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.10,
        categorical_features=[categorical_idx],
        **params
    )
    lower_model.fit(X_train, y_train_residual)

    upper_model = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=0.90,
        categorical_features=[categorical_idx],
        **params
    )
    upper_model.fit(X_train, y_train_residual)

    return lower_model, upper_model


def build_fairness_table(
    test_df: pd.DataFrame,
    y_test: np.ndarray,
    y_pred: np.ndarray,
    y_lower: np.ndarray,
    y_upper: np.ndarray,
    baseline_pred: np.ndarray,
) -> pd.DataFrame:
    """
    Compute slice-based error analysis across:
    1. Station
    2. Season (Smog: Oct-Feb vs Non-Smog: Mar-Sep)
    3. Pollution Tier (<55, 55-150, >150 ug/m3)
    """
    eval_df = test_df.copy()
    eval_df["y_true"] = y_test
    eval_df["y_pred"] = y_pred
    eval_df["y_lower"] = y_lower
    eval_df["y_upper"] = y_upper
    eval_df["baseline_pred"] = baseline_pred

    st_col = "station_slug" if "station_slug" in eval_df.columns else "station_id"

    # Season classification (Smog: Oct-Feb vs Non-Smog: Mar-Sep)
    month = pd.to_datetime(eval_df["pkt_date"]).dt.month if "pkt_date" in eval_df.columns else eval_df["calendar_month"]
    eval_df["season"] = np.where(month.isin([10, 11, 12, 1, 2]), "Smog (Oct-Feb)", "Non-Smog (Mar-Sep)")

    # Pollution Tier based on actual next-day PM2.5 (<55, 55-150, >150)
    eval_df["pollution_tier"] = pd.cut(
        eval_df["y_true"],
        bins=[-np.inf, 55.0, 150.0, np.inf],
        labels=["<55 (Low/Mod)", "55-150 (Unhealthy)", ">150 (Hazardous)"]
    )

    rows = []

    def compute_slice_metrics(slice_df: pd.DataFrame, category: str, value: str):
        if slice_df.empty:
            rows.append({
                "group_category": category,
                "group_value": str(value),
                "n_samples": 0,
                "baseline_mae": np.nan,
                "model_mae": np.nan,
                "mae_improvement_pct": np.nan,
                "rmse": np.nan,
                "coverage_80pct": np.nan,
            })
            return
        n = len(slice_df)
        base_mae = mean_absolute_error(slice_df["y_true"], slice_df["baseline_pred"])
        model_mae = mean_absolute_error(slice_df["y_true"], slice_df["y_pred"])
        rmse = root_mean_squared_error(slice_df["y_true"], slice_df["y_pred"])
        impr_pct = ((base_mae - model_mae) / base_mae * 100.0) if base_mae > 0 else 0.0

        # Coverage: fraction of actual targets within [lower_10, upper_90]
        in_bounds = (slice_df["y_true"] >= slice_df["y_lower"]) & (slice_df["y_true"] <= slice_df["y_upper"])
        coverage_80 = (in_bounds.sum() / n) * 100.0

        rows.append({
            "group_category": category,
            "group_value": str(value),
            "n_samples": n,
            "baseline_mae": round(base_mae, 2),
            "model_mae": round(model_mae, 2),
            "mae_improvement_pct": round(impr_pct, 1),
            "rmse": round(rmse, 2),
            "coverage_80pct": round(coverage_80, 1),
        })

    # Overall benchmark
    compute_slice_metrics(eval_df, "overall", "all_test_samples")

    # 1. By Station
    for st_val, grp in eval_df.groupby(st_col):
        compute_slice_metrics(grp, "station", st_val)

    # 2. By Season
    for s_val, grp in eval_df.groupby("season"):
        compute_slice_metrics(grp, "season", s_val)

    # 3. By Pollution Tier
    for t_val, grp in eval_df.groupby("pollution_tier", observed=False):
        compute_slice_metrics(grp, "pollution_tier", t_val)

    fairness_df = pd.DataFrame(rows)
    return fairness_df


def run_model_pipeline(daily_path: Path = DAILY_PATH) -> bool:
    """
    Execute complete end-to-end training, uncertainty estimation, fairness audit,
    and prediction generation pipeline.
    """
    logger.info("Starting Model Training, Uncertainty & Fairness Pipeline (Chapters 7 & 8)...")
    if not daily_path.exists():
        raise FileNotFoundError(f"Daily mart file not found at {daily_path}")

    raw_df = pd.read_parquet(daily_path)
    
    # Exclude unverified IEEE station per licensing rules
    st_col = "station_slug" if "station_slug" in raw_df.columns else "station_id"
    raw_df = raw_df[~raw_df[st_col].str.contains("ieee", case=False, na=False)].copy()

    target_col = "target_next_day_pm25"
    date_col = "pkt_date" if "pkt_date" in raw_df.columns else "date_pkt"
    valid_mask = raw_df[target_col].notna()
    if "is_valid_day" in raw_df.columns:
        valid_mask = valid_mask & raw_df["is_valid_day"].eq(True)

    # Benchmark training & evaluation partition (up to 2026-10-19)
    df = raw_df[valid_mask & (raw_df[date_col] <= "2026-10-19")].copy().reset_index(drop=True)
    if len(df) < 50:
        raise ValueError(f"Insufficient valid daily samples for modeling: {len(df)} rows found.")

    logger.info(f"Loaded {len(df)} valid daily benchmark samples across {df[st_col].nunique()} stations.")

    # Feature Engineering for benchmark models
    df, all_num_cols = prepare_features(df)
    assert not [c for c in all_num_cols if c.startswith("next_") or c.endswith("_change")], \
        "next-day weather leaked into features"

    # Chronological Split: 70% Train, 15% Val, 15% Test
    train_df, val_df, test_df = chronological_split(df, train_frac=0.70, val_frac=0.15)

    # 3 Sequential Experimental Iterations (Optimization Log)
    opt_records = []

    # Iteration 1: HistGradientBoosting Direct Target Prediction (Core features)
    core_features = [
        "pm25_daily_mean",
        "pm25_lag_1d",
        "weather_temp_mean_c",
        "weather_rh_mean_pct",
        "weather_wind_mean_kmh"
    ]
    core_features = [c for c in core_features if c in all_num_cols]
    res_it1 = train_and_evaluate_iteration(
        name="HistGradientBoosting_DirectTarget",
        feature_cols=core_features,
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        predict_residual=False,
        hgb_params={"loss": "squared_error", "max_iter": 50, "random_state": 42}
    )
    opt_records.append({
        "iteration": 1,
        "model_name": res_it1["name"],
        "valid_mae": res_it1["valid_mae"],
        "test_mae": res_it1["test_mae"],
        "baseline_test_mae": res_it1["baseline_test_mae"],
        "improvement_pct": res_it1["improvement_pct"],
        "runtime_seconds": res_it1["runtime_seconds"],
        "peak_memory_mb": res_it1["peak_memory_mb"],
        "status": "pending",
        "notes": "Direct next-day PM2.5 prediction using core historical features."
    })

    # Iteration 2: HistGradientBoosting Residual Delta Learning (Lags + Weather)
    it2_features = [
        "pm25_daily_mean",
        "pm25_lag_1d",
        "pm25_diff_1d",
        "pm25_diff_2d",
        "pm25_diff_7d",
        "pm25_lag_7d_rolling_mean",
        "city_mean",
        "city_diff",
        "weather_temp_mean_c",
        "weather_temp_max_c",
        "weather_rh_mean_pct",
        "weather_wind_mean_kmh",
        "weather_wind_max_kmh",
        "weather_precip_sum_mm",
        "calendar_month",
        "calendar_day_of_week"
    ]
    it2_features = [c for c in it2_features if c in all_num_cols]
    res_it2 = train_and_evaluate_iteration(
        name="HistGradientBoosting_ResidualDelta",
        feature_cols=it2_features,
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        predict_residual=True,
        hgb_params={"loss": "absolute_error", "learning_rate": 0.05, "max_iter": 80, "max_leaf_nodes": 15, "l2_regularization": 2.0, "random_state": 42}
    )
    opt_records.append({
        "iteration": 2,
        "model_name": res_it2["name"],
        "valid_mae": res_it2["valid_mae"],
        "test_mae": res_it2["test_mae"],
        "baseline_test_mae": res_it2["baseline_test_mae"],
        "improvement_pct": res_it2["improvement_pct"],
        "runtime_seconds": res_it2["runtime_seconds"],
        "peak_memory_mb": res_it2["peak_memory_mb"],
        "status": "pending",
        "notes": "Persistence residual delta framing with lag differences and citywide cross-station dynamics."
    })

    # Iteration 3: HistGradientBoosting City Trend Momentum & L2 Regularization (Same-day only)
    final_features = all_num_cols
    res_it3 = train_and_evaluate_iteration(
        name="HistGradientBoosting_CityTrendL2",
        feature_cols=final_features,
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        predict_residual=True,
        hgb_params={
            "loss": "quantile",
            "quantile": 0.50,
            "learning_rate": 0.05,
            "max_iter": 100,
            "max_leaf_nodes": 20,
            "l2_regularization": 10.0,
            "random_state": 42
        }
    )
    opt_records.append({
        "iteration": 3,
        "model_name": res_it3["name"],
        "valid_mae": res_it3["valid_mae"],
        "test_mae": res_it3["test_mae"],
        "baseline_test_mae": res_it3["baseline_test_mae"],
        "improvement_pct": res_it3["improvement_pct"],
        "runtime_seconds": res_it3["runtime_seconds"],
        "peak_memory_mb": res_it3["peak_memory_mb"],
        "status": "pending",
        "notes": "City trend momentum, quantile loss, L2 regularization. Same-day information only."
    })

    # Save Optimization Log and select best model by VALIDATION MAE only
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [res_it1, res_it2, res_it3]
    best_res = min(candidates, key=lambda r: r["valid_mae"])
    for rec, res in zip(opt_records, candidates):
        rec["status"] = "selected_by_validation_mae" if res is best_res else "not_selected"
    opt_records[candidates.index(best_res)]["notes"] += " Selected: lowest validation MAE."
    pd.DataFrame(opt_records).to_csv(OPTIMIZATION_LOG_CSV, index=False)
    TARGET_IMPROVEMENT_PCT = 15.0  # declared on 19 Oct (commits 40eb664 / 338cd28)
    verdict = "MET" if best_res["improvement_pct"] >= TARGET_IMPROVEMENT_PCT else "NOT MET"
    logger.info(f"Declared target >= {TARGET_IMPROVEMENT_PCT}% MAE improvement: {verdict}")
    logger.info(
        f"Final Model Test MAE: {best_res['test_mae']} vs Baseline MAE: {best_res['baseline_test_mae']} "
        f"({best_res['improvement_pct']}% improvement)"
    )

    # Uncertainty Quantile Models (10th and 90th percentiles)
    imputer = best_res["imputer"]
    encoder = best_res["encoder"]
    f_cols = best_res["feature_cols"]

    X_train_imp = imputer.transform(train_df[f_cols])
    st_train = encoder.transform(train_df[[st_col]])
    X_train_all = np.hstack([X_train_imp, st_train])
    y_train_residual = train_df[target_col].values - train_df["pm25_daily_mean"].values

    cat_idx = X_train_all.shape[1] - 1
    lower_model, upper_model = train_quantile_models(
        X_train_all,
        y_train_residual,
        categorical_idx=cat_idx,
        hgb_params={
            "learning_rate": 0.05,
            "max_iter": 100,
            "max_leaf_nodes": 20,
            "l2_regularization": 10.0,
            "random_state": 42
        }
    )

    # Evaluate Test Uncertainty Intervals
    X_test_imp = imputer.transform(test_df[f_cols])
    st_test = encoder.transform(test_df[[st_col]])
    X_test_all = np.hstack([X_test_imp, st_test])

    test_pred_point = best_res["test_preds"]
    test_pred_lower = test_df["pm25_daily_mean"].values + lower_model.predict(X_test_all)
    test_pred_upper = test_df["pm25_daily_mean"].values + upper_model.predict(X_test_all)

    # Enforce strict quantile monotonicity
    test_pred_lower = np.minimum(test_pred_lower, test_pred_point)
    test_pred_upper = np.maximum(test_pred_upper, test_pred_point)

    # Build Slice-Based Fairness Tables
    baseline_test = test_df["pm25_daily_mean"].values
    fairness_df = build_fairness_table(
        test_df=test_df,
        y_test=test_df[target_col].values,
        y_pred=test_pred_point,
        y_lower=test_pred_lower,
        y_upper=test_pred_upper,
        baseline_pred=baseline_test,
    )
    fairness_df.to_csv(ERRORS_BY_GROUP_CSV, index=False)
    logger.info(f"Saved group fairness breakdown to {ERRORS_BY_GROUP_CSV}")

    # Generate Full Predictions Output across all valid station-days
    valid_days_df = raw_df[raw_df["is_valid_day"].eq(True)].copy().reset_index(drop=True) if "is_valid_day" in raw_df.columns else raw_df.copy().reset_index(drop=True)
    full_feat_df, _ = prepare_features(valid_days_df)

    X_full_imp = imputer.transform(full_feat_df[f_cols])
    st_full = encoder.transform(full_feat_df[[st_col]])
    X_full_all = np.hstack([X_full_imp, st_full])

    full_point = full_feat_df["pm25_daily_mean"].values + best_res["model"].predict(X_full_all)
    full_lower = full_feat_df["pm25_daily_mean"].values + lower_model.predict(X_full_all)
    full_upper = full_feat_df["pm25_daily_mean"].values + upper_model.predict(X_full_all)

    full_lower = np.minimum(full_lower, full_point)
    full_upper = np.maximum(full_upper, full_point)

    date_col = "pkt_date" if "pkt_date" in full_feat_df.columns else "date_pkt"
    split_labels = []
    train_dates = set(train_df[date_col].unique())
    val_dates = set(val_df[date_col].unique())
    for d, has_target in zip(full_feat_df[date_col], full_feat_df[target_col].notna()):
        if not has_target:
            split_labels.append("live_forecast")
        elif d in train_dates:
            split_labels.append("train")
        elif d in val_dates:
            split_labels.append("validation")
        else:
            split_labels.append("test")

    target_dates = (pd.to_datetime(full_feat_df[date_col]) + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")

    pred_out_df = pd.DataFrame({
        "record_id": full_feat_df["record_id"] if "record_id" in full_feat_df.columns else full_feat_df[st_col] + "_" + full_feat_df[date_col],
        "station_slug": full_feat_df[st_col],
        "pkt_date": full_feat_df[date_col],
        "target_date": target_dates,
        "pm25_daily_mean": round(full_feat_df["pm25_daily_mean"], 2),
        "target_next_day_pm25": round(full_feat_df[target_col], 2),
        "baseline_pred_next_day_pm25": round(full_feat_df["pm25_daily_mean"], 2),
        "pred_lower_10": np.round(full_lower, 2),
        "pred_pm25": np.round(full_point, 2),
        "pred_upper_90": np.round(full_upper, 2),
        "split": split_labels,
    })

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    pred_out_df.to_parquet(PREDICTIONS_PARQUET, index=False)
    pred_out_df.to_csv(PREDICTIONS_CSV, index=False)
    logger.info(
        f"Saved {len(pred_out_df)} predictions to {PREDICTIONS_PARQUET} and {PREDICTIONS_CSV}."
    )

    export_evidence_artifacts(
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        best_res=best_res,
        opt_records=opt_records,
        st_col=st_col,
        date_col=date_col,
        target_col=target_col,
    )

    return True


def export_evidence_artifacts(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    best_res: Dict[str, Any],
    opt_records: List[Dict[str, Any]],
    st_col: str,
    date_col: str,
    target_col: str,
) -> None:
    """Export synchronized metrics JSONs and test predictions CSVs for RAG and dashboard."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    y_test_true = test_df[target_col].values.astype(float)
    y_test_base = test_df["pm25_daily_mean"].values.astype(float)
    y_test_ml = best_res["test_preds"].astype(float)

    # 1. Test prediction CSVs
    station_names = test_df["station_name"].values if "station_name" in test_df.columns else test_df[st_col].values
    record_ids = test_df["record_id"].values if "record_id" in test_df.columns else (test_df[st_col] + "_" + test_df[date_col]).values

    ml_residual = y_test_true - y_test_ml
    base_residual = y_test_true - y_test_base
    ml_abs_err = np.abs(ml_residual)
    base_abs_err = np.abs(base_residual)

    ml_preds_df = pd.DataFrame({
        "record_id": record_ids,
        "station_slug": test_df[st_col].values,
        "station_name": station_names,
        "pkt_date": test_df[date_col].values,
        "pm25_daily_mean": y_test_base,
        "target_next_day_pm25": y_test_true,
        "persistence_prediction": y_test_base,
        "ml_prediction": y_test_ml,
        "persistence_residual": base_residual,
        "ml_residual": ml_residual,
        "persistence_absolute_error": base_abs_err,
        "ml_absolute_error": ml_abs_err,
    })
    ml_preds_csv_path = PROCESSED_DIR / "pm25_hist_gradient_boosting_test_predictions.csv"
    ml_preds_df.to_csv(ml_preds_csv_path, index=False)
    logger.info(f"Saved {len(ml_preds_df)} test predictions to {ml_preds_csv_path}")

    base_preds_df = pd.DataFrame({
        "record_id": record_ids,
        "station_slug": test_df[st_col].values,
        "station_name": station_names,
        "pkt_date": test_df[date_col].values,
        "is_valid_day": test_df["is_valid_day"].values if "is_valid_day" in test_df.columns else True,
        "pm25_daily_mean": y_test_base,
        "prediction_next_day_pm25": y_test_base,
        "target_next_day_pm25": y_test_true,
        "residual": base_residual,
        "absolute_error": base_abs_err,
    })
    base_preds_csv_path = PROCESSED_DIR / "persistence_baseline_test_predictions.csv"
    base_preds_df.to_csv(base_preds_csv_path, index=False)
    logger.info(f"Saved {len(base_preds_df)} test predictions to {base_preds_csv_path}")

    # Helper for split metadata
    def get_split_meta(split_name: str, split_df: pd.DataFrame) -> Dict[str, Any]:
        dates = sorted(split_df[date_col].dropna().unique())
        return {
            "name": split_name,
            "start_date": str(dates[0]) if dates else "",
            "end_date": str(dates[-1]) if dates else "",
            "unique_dates": int(len(dates)),
            "sample_count": int(len(split_df)),
            "station_count": int(split_df[st_col].nunique()),
        }

    splits_dict = {
        "train": get_split_meta("train", train_df),
        "validation": get_split_meta("validation", val_df),
        "test": get_split_meta("test", test_df),
    }

    # Station-wise test metrics
    overall_sample_count = int(len(test_df))
    overall_base_mae = float(mean_absolute_error(y_test_true, y_test_base))
    overall_base_rmse = float(root_mean_squared_error(y_test_true, y_test_base))
    overall_ml_mae = float(mean_absolute_error(y_test_true, y_test_ml))
    overall_ml_rmse = float(root_mean_squared_error(y_test_true, y_test_ml))
    overall_mae_impr = float(((overall_base_mae - overall_ml_mae) / overall_base_mae) * 100.0) if overall_base_mae > 0 else 0.0
    overall_rmse_impr = float(((overall_base_rmse - overall_ml_rmse) / overall_base_rmse) * 100.0) if overall_base_rmse > 0 else 0.0

    by_station_ml = []
    by_station_base = []
    for slug, grp in test_df.groupby(st_col):
        idxs = grp.index
        # Locate indices in test_df
        locs = test_df.index.get_indexer(idxs)
        st_true = y_test_true[locs]
        st_base = y_test_base[locs]
        st_ml = y_test_ml[locs]
        st_count = int(len(st_true))
        st_name = str(grp["station_name"].iloc[0]) if "station_name" in grp.columns else str(slug)

        st_base_mae = float(mean_absolute_error(st_true, st_base))
        st_base_rmse = float(root_mean_squared_error(st_true, st_base))
        st_ml_mae = float(mean_absolute_error(st_true, st_ml))
        st_ml_rmse = float(root_mean_squared_error(st_true, st_ml))
        st_mae_impr = float(((st_base_mae - st_ml_mae) / st_base_mae) * 100.0) if st_base_mae > 0 else 0.0
        st_rmse_impr = float(((st_base_rmse - st_ml_rmse) / st_base_rmse) * 100.0) if st_base_rmse > 0 else 0.0

        by_station_ml.append({
            "station_slug": str(slug),
            "sample_count": st_count,
            "persistence": {
                "mae": st_base_mae,
                "rmse": st_base_rmse,
            },
            "ml": {
                "mae": st_ml_mae,
                "rmse": st_ml_rmse,
            },
            "mae_improvement_pct": st_mae_impr,
            "rmse_improvement_pct": st_rmse_impr,
            "station_name": st_name,
        })

        by_station_base.append({
            "station_slug": str(slug),
            "mae": st_base_mae,
            "rmse": st_base_rmse,
            "sample_count": st_count,
            "station_name": st_name,
        })

    # Persistence baseline metrics JSON
    persistence_metrics_data = {
        "model": "persistence",
        "prediction_column": "pm25_daily_mean",
        "target_column": target_col,
        "split_method": "chronological by unique eligible PKT dates",
        "fractions": {
            "train": 0.70,
            "validation": 0.15,
            "test": 0.15,
        },
        "splits": splits_dict,
        "test_metrics": {
            "overall": {
                "mae": overall_base_mae,
                "rmse": overall_base_rmse,
                "sample_count": overall_sample_count,
            },
            "by_station": by_station_base,
        },
    }
    persistence_json_path = REPORTS_DIR / "persistence_baseline_metrics.json"
    with open(persistence_json_path, "w", encoding="utf-8") as f:
        json.dump(persistence_metrics_data, f, indent=2)
    logger.info(f"Saved persistence baseline metrics to {persistence_json_path}")

    # ML model metrics JSON
    candidates_meta = []
    for idx, rec in enumerate(opt_records):
        candidates_meta.append({
            "candidate_index": idx,
            "model_name": rec["model_name"],
            "validation_mae": float(rec["valid_mae"]),
            "test_mae": float(rec["test_mae"]),
            "improvement_pct": float(rec["improvement_pct"]),
        })

    ml_metrics_data = {
        "model": "HistGradientBoostingRegressor",
        "selected_iteration": best_res["name"],
        "target_column": target_col,
        "prediction_time_information": "end of completed prediction day",
        "features": {
            "categorical": [st_col],
            "numeric": best_res["feature_cols"],
        },
        "model_selection": {
            "selection_metric": "validation_mae",
            "candidates": candidates_meta,
            "selected_candidate_iteration": best_res["name"],
            "selected_validation_mae": float(best_res["valid_mae"]),
        },
        "split_method": "chronological by unique eligible PKT dates",
        "splits": splits_dict,
        "test_metrics": {
            "overall": {
                "sample_count": overall_sample_count,
                "persistence": {
                    "mae": overall_base_mae,
                    "rmse": overall_base_rmse,
                },
                "ml": {
                    "mae": overall_ml_mae,
                    "rmse": overall_ml_rmse,
                },
                "mae_improvement_pct": overall_mae_impr,
                "rmse_improvement_pct": overall_rmse_impr,
            },
            "by_station": by_station_ml,
        },
    }
    ml_json_path = REPORTS_DIR / "pm25_hist_gradient_boosting_metrics.json"
    with open(ml_json_path, "w", encoding="utf-8") as f:
        json.dump(ml_metrics_data, f, indent=2)
    logger.info(f"Saved model metrics to {ml_json_path}")


if __name__ == "__main__":
    try:
        run_model_pipeline()
    except Exception as e:
        logger.error(f"Model pipeline failed: {e}", exc_info=True)
        sys.exit(1)
