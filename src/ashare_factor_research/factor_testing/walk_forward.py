from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_factor_research.factor_testing.ic_test import calc_ic
from ashare_factor_research.utils.helpers import require_columns


def _mean_rank_ic(frame: pd.DataFrame, factor: str, return_col: str) -> float:
    series = calc_ic(frame, factor, return_col=return_col, method="spearman")
    return float(series.mean()) if not series.empty else np.nan


def build_walk_forward_scores(
    panel: pd.DataFrame,
    factor_cols: list[str],
    rebalance_dates: pd.DatetimeIndex,
    return_col: str,
    *,
    train_months: int = 24,
    validation_months: int = 6,
    min_train_dates: int = 6,
    min_abs_ic: float = 0.01,
    min_coverage: float = 0.3,
    require_validation_sign: bool = True,
    max_factors: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Create strictly lagged factor directions and weights for each test date."""

    require_columns(panel, ["trade_date", "ts_code", return_col, *factor_cols], "factor_panel")
    data = panel.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    if "target_return_end_date" in data:
        data["target_return_end_date"] = pd.to_datetime(data["target_return_end_date"])
    scored_rows: list[pd.DataFrame] = []
    ic_rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    anomaly_rows: list[dict[str, object]] = []

    for test_date in pd.DatetimeIndex(pd.to_datetime(rebalance_dates)).sort_values():
        validation_start = test_date - pd.DateOffset(months=validation_months)
        train_start = validation_start - pd.DateOffset(months=train_months)
        train = data[data["trade_date"].between(train_start, validation_start, inclusive="left")]
        validation = data[data["trade_date"].between(validation_start, test_date, inclusive="left")]
        if "target_return_end_date" in data:
            train = train[train["target_return_end_date"] < validation_start]
            validation = validation[validation["target_return_end_date"] < test_date]
        if train["trade_date"].nunique() < min_train_dates:
            anomaly_rows.append({
                "test_date": test_date,
                "factor": "__window__",
                "flag": "insufficient_train_dates",
                "value": int(train["trade_date"].nunique()),
            })
            continue
        candidates: list[dict[str, object]] = []
        for factor in factor_cols:
            coverage = float(train[factor].notna().mean()) if len(train) else 0.0
            train_ic = _mean_rank_ic(train, factor, return_col)
            validation_ic = _mean_rank_ic(validation, factor, return_col) if not validation.empty else np.nan
            direction = 1.0 if train_ic >= 0 else -1.0
            sign_ok = pd.isna(validation_ic) or np.sign(validation_ic) == np.sign(train_ic)
            selected = bool(
                coverage >= min_coverage
                and pd.notna(train_ic)
                and abs(train_ic) >= min_abs_ic
                and (sign_ok or not require_validation_sign)
            )
            ic_rows.append(
                {
                    "test_date": test_date,
                    "factor": factor,
                    "train_start": train_start,
                    "train_end": validation_start,
                    "validation_start": validation_start,
                    "validation_end": test_date,
                    "train_rank_ic": train_ic,
                    "validation_rank_ic": validation_ic,
                    "coverage": coverage,
                    "direction": direction,
                    "selected": selected,
                }
            )
            if selected:
                candidates.append({"factor": factor, "direction": direction, "strength": abs(train_ic)})
            if pd.notna(train_ic) and abs(train_ic) > 0.3:
                anomaly_rows.append(
                    {"test_date": test_date, "factor": factor, "flag": "extreme_train_ic", "value": train_ic}
                )
            if coverage < min_coverage:
                anomaly_rows.append(
                    {"test_date": test_date, "factor": factor, "flag": "low_coverage", "value": coverage}
                )
        candidates = sorted(candidates, key=lambda item: float(item["strength"]), reverse=True)
        if max_factors is not None:
            candidates = candidates[:max_factors]
        if not candidates:
            anomaly_rows.append({
                "test_date": test_date,
                "factor": "__window__",
                "flag": "no_factor_selected",
                "value": 0,
            })
            continue
        strength_sum = sum(float(item["strength"]) for item in candidates)
        test = data[data["trade_date"].eq(test_date)].copy()
        test["score"] = 0.0
        test["available_factor_count"] = 0
        test["available_weight"] = 0.0
        for item in candidates:
            factor = str(item["factor"])
            weight = float(item["strength"]) / strength_sum
            direction = float(item["direction"])
            available = test[factor].notna()
            test.loc[available, "score"] += test.loc[available, factor].astype(float) * direction * weight
            test.loc[available, "available_factor_count"] += 1
            test.loc[available, "available_weight"] += weight
            weight_rows.append(
                {
                    "test_date": test_date,
                    "factor": factor,
                    "direction": direction,
                    "weight": weight,
                }
            )
        test.loc[test["available_factor_count"].eq(0), "score"] = np.nan
        valid_weight = test["available_weight"].gt(0)
        test.loc[valid_weight, "score"] /= test.loc[valid_weight, "available_weight"]
        scored_rows.append(test[["trade_date", "ts_code", "score", "available_factor_count", return_col]])

    scores = pd.concat(scored_rows, ignore_index=True) if scored_rows else pd.DataFrame(
        columns=["trade_date", "ts_code", "score", "available_factor_count", return_col]
    )
    oos_rows = []
    for date, part in scores.groupby("trade_date"):
        valid = part[["score", return_col]].dropna()
        oos_ic = (
            valid["score"].rank(method="average").corr(valid[return_col].rank(method="average"), method="pearson")
            if len(valid) >= 3 else np.nan
        )
        oos_rows.append({"test_date": date, "oos_score_rank_ic": oos_ic, "asset_count": len(valid)})
    return {
        "scores": scores,
        "window_ic": pd.DataFrame(ic_rows),
        "weights": pd.DataFrame(weight_rows),
        "oos_ic": pd.DataFrame(oos_rows),
        "anomalies": pd.DataFrame(anomaly_rows),
    }
