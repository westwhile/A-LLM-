"""Low-search, fixed linear evaluator for R1 representation comparisons.

The evaluator is intentionally small: it measures whether adding a text
representation changes out-of-sample predictions while keeping the model,
sample and time split fixed.  Model selection belongs to R2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ashare_factor_research.data.provenance import dataframe_sha256
from ashare_factor_research.utils.helpers import require_columns


R1_EVALUATOR_VERSION = "r1_fixed_linear_evaluator_v1"


@dataclass(frozen=True)
class FrozenLinearEvaluatorSpec:
    evaluator_id: str
    train_months: int = 24
    embargo_days: int = 0
    ridge_alpha: float = 0.0
    min_train_dates: int = 6
    min_assets_per_test_date: int = 3
    standardize: bool = True
    final_holdout_start: str | None = None


def validate_frozen_evaluator_spec(spec: FrozenLinearEvaluatorSpec) -> None:
    if not spec.evaluator_id.strip():
        raise ValueError("evaluator_id must be non-empty")
    if spec.train_months <= 0:
        raise ValueError("train_months must be positive")
    if spec.embargo_days < 0:
        raise ValueError("embargo_days must be non-negative")
    if spec.ridge_alpha < 0:
        raise ValueError("ridge_alpha must be non-negative")
    if spec.min_train_dates < 2:
        raise ValueError("min_train_dates must be at least 2")
    if spec.min_assets_per_test_date < 3:
        raise ValueError("min_assets_per_test_date must be at least 3")
    if spec.final_holdout_start is not None:
        pd.Timestamp(spec.final_holdout_start)


def evaluator_spec_sha256(spec: FrozenLinearEvaluatorSpec) -> str:
    validate_frozen_evaluator_spec(spec)
    payload = {"evaluator_version": R1_EVALUATOR_VERSION, **asdict(spec)}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def evaluate_representation_increment(
    panel: pd.DataFrame,
    *,
    base_features: list[str],
    text_features: list[str],
    spec: FrozenLinearEvaluatorSpec,
    target_col: str = "target_return",
    signal_date_col: str = "signal_date",
    label_end_date_col: str = "label_end_date",
    asset_col: str = "ts_code",
    allow_final_holdout: bool = False,
    final_holdout_access_ref: str | None = None,
) -> dict[str, pd.DataFrame | dict[str, Any]]:
    """Compare base and base+text on the exact same OOS rows.

    All declared features must already be point-in-time and missingness-aware.
    The function refuses implicit imputation: if text absence is meaningful,
    callers must add an explicit coverage feature and a predeclared fill rule.
    """

    validate_frozen_evaluator_spec(spec)
    if target_col in set(base_features + text_features):
        raise ValueError("target column cannot be used as a feature")
    if set(base_features) & set(text_features):
        raise ValueError("base_features and text_features must be disjoint")
    if len(set(base_features + text_features)) != len(base_features + text_features):
        raise ValueError("feature names must be unique")
    required = [signal_date_col, label_end_date_col, asset_col, target_col, *base_features, *text_features]
    require_columns(panel, required, "r1_evaluator_panel")
    data = panel.copy()
    data[signal_date_col] = pd.to_datetime(data[signal_date_col], errors="coerce")
    data[label_end_date_col] = pd.to_datetime(data[label_end_date_col], errors="coerce")
    if data[[signal_date_col, label_end_date_col]].isna().any().any():
        raise ValueError("signal_date and label_end_date must be parseable")
    if (data[label_end_date_col] <= data[signal_date_col]).any():
        raise ValueError("label_end_date must be later than signal_date")
    if data.duplicated([signal_date_col, asset_col]).any():
        raise ValueError("evaluator panel must be unique by signal date and asset")
    feature_columns = base_features + text_features
    numeric = data[[*feature_columns, target_col]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        missing = numeric.columns[numeric.isna().any()].tolist()
        raise ValueError(
            "evaluator refuses implicit feature/target imputation; missing or nonnumeric columns: "
            f"{missing}"
        )
    data[[*feature_columns, target_col]] = numeric

    if spec.final_holdout_start is not None:
        holdout_start = pd.Timestamp(spec.final_holdout_start)
        touches_holdout = data[signal_date_col].ge(holdout_start).any()
        if touches_holdout and allow_final_holdout and not final_holdout_access_ref:
            raise ValueError("final holdout access requires final_holdout_access_ref")
    else:
        holdout_start = None

    prediction_rows: list[dict[str, object]] = []
    metric_rows: list[dict[str, object]] = []
    dates = pd.DatetimeIndex(data[signal_date_col].sort_values().unique())
    for test_date in dates:
        if holdout_start is not None and test_date >= holdout_start and not allow_final_holdout:
            continue
        train_start = test_date - pd.DateOffset(months=spec.train_months)
        purge_cutoff = test_date - pd.Timedelta(days=spec.embargo_days)
        train = data[
            data[signal_date_col].between(train_start, test_date, inclusive="left")
            & data[label_end_date_col].lt(purge_cutoff)
        ].copy()
        test = data[data[signal_date_col].eq(test_date)].copy()
        if train[signal_date_col].nunique() < spec.min_train_dates:
            continue
        if len(test) < spec.min_assets_per_test_date:
            continue
        train_label_end_max = train[label_end_date_col].max()
        if not pd.Timestamp(train_label_end_max) < purge_cutoff:
            raise ValueError("purge/embargo invariant failed")
        for variant, features in (("base", base_features), ("base_plus_text", base_features + text_features)):
            predictions = _fit_predict_linear(
                train[features],
                train[target_col],
                test[features],
                alpha=spec.ridge_alpha,
                standardize=spec.standardize,
            )
            actual = test[target_col].to_numpy(dtype=float)
            rank_ic = _rank_correlation(predictions, actual)
            mse = float(np.mean((predictions - actual) ** 2))
            metric_rows.append(
                {
                    "test_date": test_date,
                    "variant": variant,
                    "rank_ic": rank_ic,
                    "mse": mse,
                    "asset_count": int(len(test)),
                    "train_date_count": int(train[signal_date_col].nunique()),
                    "train_start": train[signal_date_col].min(),
                    "train_end": train[signal_date_col].max(),
                    "train_label_end_max": train_label_end_max,
                    "purge_cutoff": purge_cutoff,
                    "leakage_check_passed": True,
                    "evaluator_spec_sha256": evaluator_spec_sha256(spec),
                }
            )
            for asset, predicted, observed in zip(test[asset_col], predictions, actual, strict=True):
                prediction_rows.append(
                    {
                        "test_date": test_date,
                        "ts_code": str(asset),
                        "variant": variant,
                        "prediction": float(predicted),
                        "actual_return": float(observed),
                        "evaluator_spec_sha256": evaluator_spec_sha256(spec),
                    }
                )
    predictions = pd.DataFrame(prediction_rows)
    metrics = pd.DataFrame(metric_rows)
    summary = _summarize_increment(metrics, spec, base_features, text_features)
    return {"predictions": predictions, "metrics": metrics, "summary": summary}


def write_r1_evaluation_artifacts(
    result: dict[str, pd.DataFrame | dict[str, Any]],
    output_dir: str | Path,
) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    predictions = result["predictions"]
    metrics = result["metrics"]
    summary = result["summary"]
    if not isinstance(predictions, pd.DataFrame) or not isinstance(metrics, pd.DataFrame) or not isinstance(summary, dict):
        raise ValueError("invalid R1 evaluator result")
    paths = {
        "predictions": root / "r1_oos_predictions.csv",
        "metrics": root / "r1_oos_metrics.csv",
        "summary": root / "r1_evaluation_summary.json",
    }
    predictions.to_csv(paths["predictions"], index=False, encoding="utf-8")
    metrics.to_csv(paths["metrics"], index=False, encoding="utf-8")
    payload = {
        **summary,
        "predictions_sha256": dataframe_sha256(predictions),
        "metrics_sha256": dataframe_sha256(metrics),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    paths["summary"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}


def build_negative_control_features(
    panel: pd.DataFrame,
    *,
    feature_cols: list[str],
    control: str,
    signal_date_col: str = "signal_date",
    asset_col: str = "ts_code",
    random_state: int = 42,
) -> pd.DataFrame:
    """Create predeclared negative controls without modifying outcomes."""

    require_columns(panel, [signal_date_col, asset_col, *feature_cols], "negative_control_panel")
    out = panel.copy()
    out[signal_date_col] = pd.to_datetime(out[signal_date_col])
    if control == "event_time_shift":
        dates = sorted(out[signal_date_col].unique())
        mapping = {date: dates[index + 1] for index, date in enumerate(dates[:-1])}
        shifted = out[[signal_date_col, asset_col, *feature_cols]].copy()
        shifted[signal_date_col] = shifted[signal_date_col].map(mapping)
        shifted = shifted.dropna(subset=[signal_date_col])
        out = out.drop(columns=feature_cols).merge(
            shifted,
            on=[signal_date_col, asset_col],
            how="inner",
            validate="one_to_one",
        )
    elif control == "stock_mapping_permutation":
        rng = np.random.default_rng(random_state)
        parts: list[pd.DataFrame] = []
        for _, group in out.groupby(signal_date_col, sort=True):
            part = group.copy()
            permutation = rng.permutation(len(part))
            part[feature_cols] = part[feature_cols].to_numpy()[permutation]
            parts.append(part)
        out = pd.concat(parts, ignore_index=True) if parts else out
    else:
        raise ValueError(f"unsupported negative control: {control}")
    out["negative_control"] = control
    out["negative_control_random_state"] = int(random_state)
    return out.sort_values([signal_date_col, asset_col], kind="mergesort").reset_index(drop=True)


def _fit_predict_linear(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    test_x: pd.DataFrame,
    *,
    alpha: float,
    standardize: bool,
) -> np.ndarray:
    x_train = train_x.to_numpy(dtype=float)
    x_test = test_x.to_numpy(dtype=float)
    y_train = train_y.to_numpy(dtype=float)
    if x_train.shape[1] == 0:
        return np.full(len(x_test), y_train.mean(), dtype=float)
    if standardize:
        mean = x_train.mean(axis=0)
        scale = x_train.std(axis=0, ddof=0)
        scale[scale == 0] = 1.0
        x_train = (x_train - mean) / scale
        x_test = (x_test - mean) / scale
    train_design = np.column_stack([np.ones(len(x_train)), x_train])
    test_design = np.column_stack([np.ones(len(x_test)), x_test])
    penalty = np.eye(train_design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.pinv(train_design.T @ train_design + penalty) @ train_design.T @ y_train
    return test_design @ beta


def _rank_correlation(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or len(np.unique(left)) < 2 or len(np.unique(right)) < 2:
        return float("nan")
    left_rank = pd.Series(left).rank(method="average")
    right_rank = pd.Series(right).rank(method="average")
    return float(left_rank.corr(right_rank, method="pearson"))


def _summarize_increment(
    metrics: pd.DataFrame,
    spec: FrozenLinearEvaluatorSpec,
    base_features: list[str],
    text_features: list[str],
) -> dict[str, Any]:
    variants: dict[str, dict[str, object]] = {}
    if not metrics.empty:
        for variant, part in metrics.groupby("variant", sort=True):
            variants[str(variant)] = {
                "test_dates": int(part["test_date"].nunique()),
                "mean_rank_ic": _finite_mean(part["rank_ic"]),
                "mean_mse": _finite_mean(part["mse"]),
            }
    base = variants.get("base", {})
    augmented = variants.get("base_plus_text", {})
    base_ic = base.get("mean_rank_ic")
    augmented_ic = augmented.get("mean_rank_ic")
    base_mse = base.get("mean_mse")
    augmented_mse = augmented.get("mean_mse")
    return {
        "schema_version": 1,
        "evaluator_version": R1_EVALUATOR_VERSION,
        "evaluator_spec": asdict(spec),
        "evaluator_spec_sha256": evaluator_spec_sha256(spec),
        "base_features": list(base_features),
        "text_features": list(text_features),
        "variants": variants,
        "increment": {
            "mean_rank_ic_delta": _difference(augmented_ic, base_ic),
            "mean_mse_reduction": _difference(base_mse, augmented_mse),
        },
        "status": "engineering_only_no_research_conclusion",
    }


def _finite_mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(numeric.mean()) if len(numeric) else None


def _difference(left: object, right: object) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)
